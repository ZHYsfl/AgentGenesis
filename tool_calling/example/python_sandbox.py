# concrete tool action : python_sandbox_tool, python_figure_sandbox_tool
# provide python sandbox environment for agent to execute python code
# provide python figure sandbox environment for agent to execute python figure code
import sys
from pathlib import Path

from matplotlib.figure import Figure
from dotenv import load_dotenv
load_dotenv(override=True)
import os
import asyncio

CURRENT_DIR = Path(__file__).resolve().parent
SDK_DIR = CURRENT_DIR.parent
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from async_tool_calling import Agent, Tool, LLMConfig

# python sandbox tool environment
def python_sandbox_tool(py_code : str, g='globals()') -> str: # python sandbox tool action
    """
    Execute Python code and get final query or processing results.
    :param py_code: Python code as string
    :param g: String form of environment variable, represents globals, no need to set, keep default
    Core function: Acts as "environment" or "namespace" (Namespace) for code execution
    :return: Final result of code execution
    """
    print("[Python Sandbox] Executing Python code...")
    try:
        if g is None or isinstance(g, str):
            g = globals()
        return str(eval(py_code, g)) # python sandbox tool observation
    # If error, test if it's duplicate assignment to same variable
    except Exception as e:
        # Ensure g is dict type
        if g is None or isinstance(g, str):
            g = globals()
        global_vars_before = set(g.keys())
        try:
            exec(py_code, g)
        except Exception as e:
            return f"[Error] Code execution error: {e}"
        global_vars_after = set(g.keys())
        new_vars = global_vars_after - global_vars_before
        # If new variables exist
        if new_vars:
            result = {var: g[var] for var in new_vars}
            print("[Python Sandbox] Code executed successfully, organizing results...")
            return f"[Success] Code executed, new variables: {result}" # python sandbox tool observation
        else:
            print("[Python Sandbox] Code executed successfully...")
            return "[Success] Code executed" # python sandbox tool observation

python_inter_args = '{"py_code": "import numpy as np\\narr = np.array([1, 2, 3, 4])\\nsum_arr = np.sum(arr)\\nsum_arr"}'
python_sandbox_tool = Tool(
    name="python_sandbox_tool",
    description=f"Call this function when user needs to write and execute Python programs. This function can execute Python code and return final results. Note: this function can only execute non-plotting code. For plotting code, use python_figure_sandbox_tool.\nAlso note: when writing external function parameter messages, they must be JSON-formatted strings. Example: {python_inter_args}",
    function=python_sandbox_tool,
    parameters={
        "type": "object",
        "properties": {
            "py_code": {
                "type": "string",
                "description": "The Python code to execute."
            },
            "g": {
                "type": "string",
                "description": "Global environment variable, keep default 'globals()'.",
                "default": "globals()"
            }
        },
        "required": ["py_code"]
    }
)

# python figure sandbox tool environment
def python_figure_sandbox_tool(py_code: str, fname: str, g='globals()') -> str: # python figure sandbox tool action
    """
    Execute Python plotting code and get final plotting results.
    :param py_code: Python code as string
    :param fname: File name as string (without extension), also used to find image variable in code
    :param g: String form of environment variable, represents globals, no need to set, keep default
    :return: Plot result save path or error message
    """
    print("[Python Figure Sandbox] Executing Python plotting code...")
    import matplotlib
    # Use non-interactive backend to avoid GUI thread issues
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import seaborn as sns
    import pandas as pd

    # ========== Chinese font configuration (avoid garbled text) ==========
    # Try different Chinese fonts in order of priority:
    # Windows: Microsoft YaHei, SimHei, SimSun
    # macOS: PingFang SC, Heiti SC, STHeiti
    # Linux: WenQuanYi Micro Hei, Noto Sans CJK SC, Droid Sans Fallback
    plt.rcParams['font.sans-serif'] = [
        'Microsoft YaHei',      # Windows Microsoft YaHei
        'SimHei',               # Windows Heiti
        'PingFang SC',          # macOS PingFang
        'Heiti SC',             # macOS Heiti
        'WenQuanYi Micro Hei',  # Linux WenQuanYi
        'Noto Sans CJK SC',     # Linux/General Source Han Sans
        'DejaVu Sans'           # Fallback English font
    ]
    plt.rcParams['axes.unicode_minus'] = False  # Fix minus sign '-' displaying as square
    # =============================================

    # Local variables for code execution
    local_vars = {"plt": plt, "pd": pd, "sns": sns}

    # Relative path save directory
    pics_dir = 'pics'
    if not os.path.exists(pics_dir):
        os.makedirs(pics_dir)

    try:
        # Execute user code
        if g is None or isinstance(g, str):
            g = globals()
        exec(py_code, g, local_vars)

        # Get figure object
        fig = local_vars.get(fname, None)
        if fig is None and plt.gcf().get_axes():
            fig = plt.gcf()

        if fig and hasattr(fig, 'get_axes') and fig.get_axes():
            rel_path = os.path.join(pics_dir, f"{fname}.png")
            fig.savefig(rel_path, bbox_inches='tight')
            if isinstance(fig, Figure):
                plt.close(fig)
            print("[Python Figure Sandbox] Code executed successfully, image saved.")
            return f"[Success] Image saved to: {rel_path}" # python figure sandbox tool observation
        elif fname in local_vars and not isinstance(local_vars[fname], Figure):
            return f"[Warning] Code executed but variable '{fname}' is not a valid Matplotlib Figure object." # python figure sandbox tool observation
        else:
            # Check if using plt directly for plotting
            if plt.gcf().get_axes():
                rel_path = os.path.join(pics_dir, f"{fname}.png")
                plt.savefig(rel_path, bbox_inches='tight')
                plt.close(plt.gcf())
                print("[Python Figure Sandbox] Code executed successfully, image saved via plt.")
                return f"[Success] Image saved to: {rel_path} (via plt)" # python figure sandbox tool observation
            else:
                return f"[Warning] Code executed but no valid figure object or plotting content found. Ensure code generates a figure and assigns to variable '{fname}' or uses plt." # python figure sandbox tool observation

    except Exception as e:
        plt.close('all')
        return f"[Error] Execution failed: {e}" # python figure sandbox tool observation

python_figure_sandbox_tool = Tool(
    name="python_figure_sandbox_tool",
    description=("Call this function when user needs Python visualization plotting tasks. "
                "This function executes user-provided Python plotting code and automatically saves generated figure objects as image files and displays them.\n\n"
                "When calling this function, pass the following parameters:\n\n"
                "1. `py_code`: Python plotting code as string, **must be complete, independently runnable script**, "
                "code must create and return a matplotlib figure object named `fname`;\n"
                "2. `fname`: Variable name of the figure object (as string), e.g., 'fig';\n"
                "3. `g`: Global environment variable, keep default 'globals()'.\n\n"
                "[Requirements for plotting code]:\n"
                "- Include all necessary imports (e.g., `import matplotlib.pyplot as plt`, `import seaborn as sns`);\n"
                "- Must include data definitions (e.g., `df = pd.DataFrame(...)`), do not rely on external variables;\n"
                "- Recommended to use `fig, ax = plt.subplots()` to explicitly create figure;\n"
                "- Use `ax` object for plotting operations (e.g., `sns.lineplot(..., ax=ax)`);\n"
                "- Finally explicitly save figure as `fname` variable (e.g., `fig = plt.gcf()`).\n\n"
                "[Note] No need to save image manually, function will auto-save and display.\n"
                "[Note] Built-in Chinese font support, can directly use Chinese titles, labels, etc., no extra font config needed.\n\n"
                "[Valid example code]:\n"
                "import matplotlib.pyplot as plt\n"
                "import seaborn as sns\n"
                "import pandas as pd\n\n"
                "df = pd.DataFrame({'x': [1, 2, 3], 'y': [4, 5, 6]})\n"
                "fig, ax = plt.subplots()\n"
                "sns.lineplot(data=df, x='x', y='y', ax=ax)\n"
                "ax.set_title('Line Plot')\n"
                "fig = plt.gcf()  # Must assign to fname specified variable\n"),
    function=python_figure_sandbox_tool,
    parameters={
        "type": "object",
        "properties": {
            "py_code": {
                "type": "string",
                "description": "Python plotting code to execute, available libraries: matplotlib.pyplot, seaborn, pandas"
            },
            "fname": {
                "type": "string",
                "description": "File name for saved image (without extension), e.g., 'my_chart'"
            },
            "g": {
                "type": "string",
                "description": "Global environment variable, keep default 'globals()'.",
                "default": "globals()"
            }
        },
        "required": ["py_code", "fname"]
    }
)

async def main():
    agent = Agent(LLMConfig(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        model=os.getenv("MODEL"),
        base_url=os.getenv("BASE_URL")
    ))
    agent.add_tool(python_sandbox_tool)
    agent.add_tool(python_figure_sandbox_tool)
    observations = [{"role": "user", "content": "Please draw a line chart with x as abscissa and y as ordinate, x from 0 to 10, y as x squared"}]
    observations_final = await agent.chat(observations)
    print(observations_final)

if __name__ == "__main__":
    asyncio.run(main())
# Notebook Tool - Dynamic Notepad for Agent
# Provides temporary memory storage during Agent execution
# Notebook is empty at the start of each run, supports CRUD during execution

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
SDK_DIR = CURRENT_DIR.parent
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from async_tool_calling import Agent, Tool, LLMConfig
from dotenv import load_dotenv
load_dotenv(override=True)
import os
from datetime import datetime
import asyncio

# =============================================================================
# Notebook - Dynamic Notepad
# =============================================================================

async def create_notebook_tools(agent: Agent = None):
    """
    Factory function: Creates an independent notebook instance.

    - Empty notebook is created when this function is called (at program start)
    - All tool functions share the same notebook during execution (via closure)
    - Notebook persists throughout the entire Agent execution
    - Only reset to empty when program is rerun
    """

    # Notebook storage: key -> {content, created_at, updated_at}
    notebook = {}

    def add_note(key: str, content: str) -> str:
        """Add a new note"""
        if key in notebook:
            return f"[Warning] Note '{key}' already exists. Use update_note to update." # add_note observation

        now = datetime.now().strftime("%H:%M:%S")
        notebook[key] = {
            'content': content,
            'created_at': now,
            'updated_at': now
        }
        return f"[Success] Note '{key}' added.\n[Content]: {content[:100]}{'...' if len(content) > 100 else ''}" # add_note observation

    def get_note(key: str) -> str:
        """Get content of a specific note"""
        if key not in notebook:
            return f"[Error] Note '{key}' not found. Available notes: {list(notebook.keys())}" # get_note observation

        note = notebook[key]
        return f"[Note] '{key}':\n{note['content']}\n\n[Created]: {note['created_at']} | [Updated]: {note['updated_at']}" # get_note observation

    def update_note(key: str, content: str) -> str:
        """Update content of an existing note"""
        if key not in notebook:
            return f"[Error] Note '{key}' not found. Use add_note first." # update_note observation

        old_content = notebook[key]['content']
        notebook[key]['content'] = content
        notebook[key]['updated_at'] = datetime.now().strftime("%H:%M:%S")

        return f"[Success] Note '{key}' updated.\n[Old]: {old_content[:50]}{'...' if len(old_content) > 50 else ''}\n[New]: {content[:100]}{'...' if len(content) > 100 else ''}" # update_note observation

    def append_note(key: str, content: str) -> str:
        """Append content to an existing note"""
        if key not in notebook:
            return f"[Error] Note '{key}' not found. Use add_note first." # append_note observation

        notebook[key]['content'] += "\n" + content
        notebook[key]['updated_at'] = datetime.now().strftime("%H:%M:%S")

        return f"[Success] Content appended to note '{key}'.\n[Appended]: {content[:100]}{'...' if len(content) > 100 else ''}\n[Total length]: {len(notebook[key]['content'])} chars" # append_note observation

    def delete_note(key: str) -> str:
        """Delete a note"""
        if key not in notebook:
            return f"[Error] Note '{key}' not found." # delete_note observation

        del notebook[key]
        remaining = list(notebook.keys()) if notebook else "empty"
        return f"[Success] Note '{key}' deleted.\n[Remaining]: {remaining}" # delete_note observation

    def list_notes() -> str:
        """List summary of all notes"""
        if not notebook:
            return "[Empty] Notebook is empty. Use add_note to add first note." # list_notes observation

        result = f"[Notebook] ({len(notebook)} notes):\n\n"
        for key, note in notebook.items():
            preview = note['content'][:80].replace('\n', ' ')
            if len(note['content']) > 80:
                preview += "..."
            result += f"[{key}] {preview}\n"
            result += f"   [Updated] {note['updated_at']}\n\n"
        return result # list_notes observation

    def get_all_notes() -> str:
        """Get full content of all notes"""
        if not notebook:
            return "[Empty] Notebook is empty." # get_all_notes observation

        result = f"[Notebook] Full content ({len(notebook)} notes):\n\n"
        result += "=" * 50 + "\n"
        for key, note in notebook.items():
            result += f"[{key}]\n"
            result += "-" * 30 + "\n"
            result += note['content'] + "\n"
            result += "=" * 50 + "\n"
        return result # get_all_notes observation

    def clear_notebook() -> str:
        """Clear entire notebook"""
        count = len(notebook)
        notebook.clear()
        return f"[Cleared] Notebook cleared. {count} notes deleted." # clear_notebook observation

    # Return all notebook operation functions and notebook reference
    return {
        'add_note': add_note,
        'get_note': get_note,
        'update_note': update_note,
        'append_note': append_note,
        'delete_note': delete_note,
        'list_notes': list_notes,
        'get_all_notes': get_all_notes,
        'clear_notebook': clear_notebook,
        '_notebook': notebook  # Internal reference for debugging
    }


# =============================================================================
# Create Tool Objects
# =============================================================================

async def build_notebook_tools(agent: Agent = None) -> list[Tool]:
    """
    Build notebook series tools and return Tool object list.
    """
    funcs = await create_notebook_tools(agent)

    tools = [
        Tool(
            name="add_note",
            description=(
                "[Add] Add a new note to the notebook.\n"
                "Used to record important information, discoveries, intermediate results, etc.\n"
                "Example: Record maze maps, save intermediate calculation values, log explored paths, etc."
            ),
            function=funcs['add_note'],
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Unique identifier for the note, e.g., 'map', 'visited_nodes', 'current_state'"
                    },
                    "content": {
                        "type": "string",
                        "description": "Note content, can be any format of text"
                    }
                },
                "required": ["key", "content"]
            }
        ),
        Tool(
            name="get_note",
            description="[Get] Get full content of a specific note",
            function=funcs['get_note'],
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Identifier of the note to get"
                    }
                },
                "required": ["key"]
            }
        ),
        Tool(
            name="update_note",
            description="[Update] Update (overwrite) content of an existing note",
            function=funcs['update_note'],
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Identifier of the note to update"
                    },
                    "content": {
                        "type": "string",
                        "description": "New note content (will overwrite original)"
                    }
                },
                "required": ["key", "content"]
            }
        ),
        Tool(
            name="append_note",
            description="[Append] Append content to an existing note (does not overwrite)",
            function=funcs['append_note'],
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Identifier of the note to append to"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to append"
                    }
                },
                "required": ["key", "content"]
            }
        ),
        Tool(
            name="delete_note",
            description="[Delete] Delete a note",
            function=funcs['delete_note'],
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Identifier of the note to delete"
                    }
                },
                "required": ["key"]
            }
        ),
        Tool(
            name="list_notes",
            description="[List] List summary (title and preview) of all notes in notebook",
            function=funcs['list_notes'],
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_all_notes",
            description="[GetAll] Get full content of all notes in notebook",
            function=funcs['get_all_notes'],
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="clear_notebook",
            description="[Clear] Clear entire notebook (use with caution)",
            function=funcs['clear_notebook'],
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]

    return tools


# =============================================================================
# Maze Environment - Agent can only see local information
# =============================================================================

async def create_maze_environment():
    """
    Create a maze environment where Agent can only interact via look and move tools.
    Cannot directly see the full map, must explore.
    """
    # Maze definition (Agent doesn't know this)
    # 0 = passable, 1 = wall
    maze = [
        [0, 0, 1, 0],
        [1, 0, 0, 0],
        [0, 0, 1, 0],
        [1, 0, 0, 0]
    ]
    rows, cols = len(maze), len(maze[0])
    start = (0, 0)
    goal = (3, 3)

    # Agent's current position
    state = {'pos': list(start), 'steps': 0}

    def look() -> str:
        """Observe current position and available directions"""
        r, c = state['pos']
        result = f"[Position]: ({r}, {c})\n"
        result += f"[Steps taken]: {state['steps']}\n\n"

        # Check if reached goal
        if (r, c) == goal:
            result += "[Success] You have reached the exit! Maze exploration successful!\n"
            return result # look observation

        # Check four directions
        directions = {
            'up': (-1, 0),
            'down': (1, 0),
            'left': (0, -1),
            'right': (0, 1)
        }

        result += "[Available directions]:\n"
        available = []
        for name, (dr, dc) in directions.items():
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                if maze[nr][nc] == 0:
                    available.append(name)
                    result += f"  [OK] {name} -> ({nr}, {nc})\n"
                else:
                    result += f"  [Wall] {name} -> wall\n"
            else:
                result += f"  [Out] {name} -> out of bounds\n"

        if not available:
            result += "\n[Warning] No available directions, you are trapped!\n"

        return result # look observation

    def move(direction: str) -> str:
        """Move in specified direction"""
        r, c = state['pos']

        directions = {
            'up': (-1, 0),
            'down': (1, 0),
            'left': (0, -1),
            'right': (0, 1)
        }

        if direction not in directions:
            return f"[Error] Invalid direction '{direction}'. Available: up, down, left, right" # move observation

        dr, dc = directions[direction]
        nr, nc = r + dr, c + dc

        # Check bounds
        if not (0 <= nr < rows and 0 <= nc < cols):
            return f"[Error] Cannot move {direction}, out of bounds!" # move observation

        # Check wall
        if maze[nr][nc] == 1:
            return f"[Error] Cannot move {direction}, wall ahead!" # move observation

        # Move successful
        state['pos'] = [nr, nc]
        state['steps'] += 1

        result = f"[Success] Moved {direction}!\n"
        result += f"[New position]: ({nr}, {nc})\n"

        # Check if reached goal
        if (nr, nc) == goal:
            result += f"\n[Congratulations] You found the exit!\n"
            result += f"[Total steps]: {state['steps']}\n"

        return result # move observation

    return look, move, state


async def build_maze_tools() -> list[Tool]:
    """Build maze exploration tools"""
    look, move, state = await create_maze_environment()

    tools = [
        Tool(
            name="look",
            description="[Look] Observe current position, view coordinates and available directions",
            function=look,
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="move",
            description="[Move] Move one step in specified direction (up/down/left/right)",
            function=move,
            parameters={
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                        "description": "Direction to move"
                    }
                },
                "required": ["direction"]
            }
        )
    ]
    return tools


# =============================================================================
# Test
# =============================================================================

async def main():
    # Create Agent
    agent = Agent(LLMConfig(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        model=os.getenv("MODEL"),
        base_url=os.getenv("BASE_URL")
    ))

    # Add notebook tools (for recording exploration process)
    notebook_tools = await build_notebook_tools(agent)
    for tool in notebook_tools:
        agent.add_tool(tool)

    # Add maze exploration tools
    maze_tools = await build_maze_tools()
    for tool in maze_tools:
        agent.add_tool(tool)

    print(f"[Agent] Started with {len(agent.tools)} tools")
    print(f"[Tools] Available: {[t.name for t in agent.tools]}")

    # Test: Real maze exploration (Agent doesn't know the global map)
    observations = [{
        "role": "user",
        "content": """You are in a maze and need to find the exit.

Rules:
1. You don't know the full maze map, can only use 'look' tool to see current position and available directions
2. Use 'move' tool to move (up/down/left/right)
3. Strongly recommend using notebook (add_note, append_note) to record explored positions and discoveries, avoid backtracking
4. Find the exit (system will notify you when you arrive)

Start exploring! Use 'look' first to see the surroundings."""
    }]

    observations_final = await agent.chat(observations)

    print("\n" + "="*60)
    print("[Exploration] Results:")
    print("="*60)
    for obs in observations_final:
        role = obs.get('role', 'unknown')
        content = obs.get('content', '')
        if content:
            print(f"\n[{role}]: {content[:1000]}{'...' if len(str(content)) > 1000 else ''}")

if __name__ == "__main__":
    asyncio.run(main())
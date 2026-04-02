"""Werewolf game environment.

Pure game logic with no I/O or protocol dependencies.
(env v1.1: DAY_LAST_WORDS 遗言阶段允许 speak)

IMPORTANT:
We separate internal routing ids from public player ids:
- Internal ids (for protocol routing): wolf_1, wolf_2, seer, witch, ...
- Public ids (for in-game targeting): player_1 ... player_6

Agents can only see/use public ids in observations and tool arguments.
"""

from __future__ import annotations

import random
from enum import Enum, auto
from typing import Any, Optional


# ── constants ────────────────────────────────────────────────────────

ALL_AGENT_IDS = ["wolf_1", "wolf_2", "seer", "witch", "villager_1", "villager_2"]
WOLF_IDS = {"wolf_1", "wolf_2"}
GOOD_IDS = {"seer", "witch", "villager_1", "villager_2"}

ROLE_LABELS = {
    "wolf_1": "狼人1",
    "wolf_2": "狼人2",
    "seer": "预言家",
    "witch": "女巫",
    "villager_1": "村民1",
    "villager_2": "村民2",
}


class Phase(Enum):
    SYNC = auto()  # 所有人 connection 进入，Judge 再发 obs
    NIGHT_WOLF = auto()
    NIGHT_WITCH = auto()
    NIGHT_SEER = auto()
    DAY_ANNOUNCE = auto()
    DAY_SPEAK = auto()
    DAY_VOTE = auto()
    DAY_LAST_WORDS = auto()
    GAME_OVER = auto()


# ── environment ──────────────────────────────────────────────────────

class WerewolfEnvironment:

    def __init__(self, case_data: dict, *, max_rounds: int = 15):
        self.seed: int = case_data.get("seed", 0)
        self.rng = random.Random(self.seed)
        self.max_rounds: int = max_rounds

        self.alive: dict[str, bool] = {aid: True for aid in ALL_AGENT_IDS}
        self.roles: dict[str, str] = {
            "wolf_1": "wolf", "wolf_2": "wolf",
            "seer": "seer", "witch": "witch",
            "villager_1": "villager", "villager_2": "villager",
        }

        # Public player ids are randomized each case to avoid leaking
        # role information through fixed identifiers.
        publics = [f"player_{i}" for i in range(1, len(ALL_AGENT_IDS) + 1)]
        shuffled_agents = list(ALL_AGENT_IDS)
        self.rng.shuffle(shuffled_agents)
        self.public_id_by_agent: dict[str, str] = {
            aid: publics[idx] for idx, aid in enumerate(shuffled_agents)
        }
        self.agent_id_by_public: dict[str, str] = {
            pub: aid for aid, pub in self.public_id_by_agent.items()
        }

        self.phase: Phase = Phase.SYNC
        self.round_num: int = 1
        self.step_count: int = 0
        self.game_log: list[str] = []

        self.wolf_kill_target: Optional[str] = None
        self.witch_has_save: bool = True
        self.witch_has_poison: bool = True
        self.witch_saved: bool = False
        self.witch_poison_target: Optional[str] = None

        self.seer_check_target: Optional[str] = None
        self.seer_check_result: Optional[str] = None

        self.night_deaths: list[str] = []

        self.speak_order: list[str] = []
        self.speak_index: int = 0
        self.speeches: dict[str, str] = {}

        self.vote_round: int = 0
        self.vote_max_rounds: int = 3
        self.votes: dict[str, Optional[str]] = {}
        self.vote_eliminated: Optional[str] = None

        self.last_words_target: Optional[str] = None

        self.winner: Optional[str] = None
        self.error_reason: Optional[str] = None

    # ── public queries ───────────────────────────────────────────────

    @property
    def done(self) -> bool:
        return self.phase == Phase.GAME_OVER

    @property
    def success(self) -> bool:
        """Pass if game ended with a real winner (wolf or good). Fail if ended due to agent error."""
        return self.winner in ("good", "wolf")

    def compute_score(self) -> int:
        """100 if good wins, 50 if wolf wins, 0 if error (agent called wrong tool)."""
        if self.winner == "good":
            return 100
        if self.winner == "wolf":
            return 50
        return 0

    def alive_ids(self) -> list[str]:
        return [a for a in ALL_AGENT_IDS if self.alive[a]]

    def alive_public_ids(self) -> list[str]:
        return [self.public_id_by_agent[a] for a in self.alive_ids()]

    def alive_wolves(self) -> list[str]:
        return [a for a in WOLF_IDS if self.alive[a]]

    def alive_good(self) -> list[str]:
        return [a for a in GOOD_IDS if self.alive[a]]

    def _is_first_day_vote_round(self) -> bool:
        """Whether current voting belongs to the first day (after night 1)."""
        return self.round_num == 1

    def pub(self, agent_id: Optional[str]) -> str:
        if not agent_id:
            return "未知"
        return self.public_id_by_agent.get(agent_id, agent_id)

    def role_name(self, agent_id: str) -> str:
        return ROLE_LABELS.get(agent_id, agent_id)

    def resolve_target_public(self, target_public: str) -> Optional[str]:
        return self.agent_id_by_public.get(str(target_public).strip())

    def _resolve_valid_vote_target(self, voter_id: str, act: dict[str, Any]) -> Optional[str]:
        """Resolve vote target and ensure it is valid (alive and not self)."""
        target_public = str(act.get("target", ""))
        target = self.resolve_target_public(target_public)
        if target in self.alive_ids() and target != voter_id:
            return target
        return None

    # ── step dispatcher ──────────────────────────────────────────────

    def build_obs(self) -> dict[str, Any]:
        """Build per-agent observation dict for the current phase."""
        handler = {
            Phase.SYNC: self._obs_sync,
            Phase.NIGHT_WOLF: self._obs_night_wolf,
            Phase.NIGHT_WITCH: self._obs_night_witch,
            Phase.NIGHT_SEER: self._obs_night_seer,
            Phase.DAY_ANNOUNCE: self._obs_day_announce,
            Phase.DAY_SPEAK: self._obs_day_speak,
            Phase.DAY_VOTE: self._obs_day_vote,
            Phase.DAY_LAST_WORDS: self._obs_day_last_words,
        }.get(self.phase)
        if handler is None:
            return {aid: "游戏已结束" for aid in ALL_AGENT_IDS}
        return handler()

    def apply_actions(self, action_dict: dict[str, Any]) -> dict[str, Any]:
        """Validate and apply the BSP action dict, advance phase, return obs.

        ``action_dict`` is keyed by agent_id.  Each value is a dict
        produced by the agent's tool call: ``{"action": "...", ...}``.
        Returns the obs dict for the *next* tick (or terminal obs).
        """
        self.step_count += 1

        err = self._validate_actions(action_dict)
        if err:
            self.error_reason = err
            self._end_game(None)
            return {aid: f"ERROR: {err}" for aid in ALL_AGENT_IDS}

        handler = {
            Phase.SYNC: self._apply_sync,
            Phase.NIGHT_WOLF: self._apply_night_wolf,
            Phase.NIGHT_WITCH: self._apply_night_witch,
            Phase.NIGHT_SEER: self._apply_night_seer,
            Phase.DAY_ANNOUNCE: self._apply_day_announce,
            Phase.DAY_SPEAK: self._apply_day_speak,
            Phase.DAY_VOTE: self._apply_day_vote,
            Phase.DAY_LAST_WORDS: self._apply_day_last_words,
        }.get(self.phase)

        if handler is None:
            return {aid: "游戏已结束" for aid in ALL_AGENT_IDS}

        handler(action_dict)

        if self.error_reason is not None:
            return {aid: self._terminal_obs(aid) for aid in ALL_AGENT_IDS}
        if self._check_game_over():
            return {aid: self._terminal_obs(aid) for aid in ALL_AGENT_IDS}

        return self.build_obs()

    # ── observation builders ─────────────────────────────────────────

    def _obs_sync(self) -> dict[str, Any]:
        """SYNC 阶段：所有人必须 connection，Judge 收到后再发 NIGHT_WOLF obs。"""
        return {
            aid: "游戏即将开始，请调用 connection() 进入游戏。"
            for aid in ALL_AGENT_IDS
        }

    def _dead_obs(self, aid: str, phase_hint: str) -> str:
        return (
            f"你({self.pub(aid)}/{self.role_name(aid)})已出局。"
            f"当前阶段：{phase_hint}。请调用 connection 等待。"
        )

    def _obs_night_wolf(self) -> dict[str, Any]:
        obs: dict[str, Any] = {}
        alive_list = ", ".join(self.alive_public_ids())
        for aid in ALL_AGENT_IDS:
            if not self.alive[aid]:
                obs[aid] = self._dead_obs(aid, "夜晚-狼人阶段")
            elif aid in WOLF_IDS:
                partner = [w for w in self.alive_wolves() if w != aid]
                partner_str = (
                    f"你的狼人同伴编号是 {self.pub(partner[0])}" if partner
                    else "你是唯一存活的狼人"
                )
                obs[aid] = (
                    f"第{self.round_num}夜，狼人阶段。你的编号是 {self.pub(aid)}。"
                    f"{partner_str}。存活玩家编号：{alive_list}。"
                    f"请调用 kill(target) 选择要杀的目标（target 必须是 player_x）。"
                )
            else:
                obs[aid] = f"第{self.round_num}夜，狼人阶段，请等待。请调用 connection。"
        return obs

    def _obs_night_witch(self) -> dict[str, Any]:
        obs: dict[str, Any] = {}
        for aid in ALL_AGENT_IDS:
            if not self.alive[aid]:
                obs[aid] = self._dead_obs(aid, "夜晚-女巫阶段")
            elif aid == "witch" and self.alive.get("witch", False):
                killed_info = (
                    f"{self.pub(self.wolf_kill_target)} 今晚被狼人杀害。"
                    if self.wolf_kill_target
                    else "今晚无人被狼人杀害。"
                )
                save_info = f"你{'还有' if self.witch_has_save else '已经用过'}解药。"
                poison_info = f"你{'还有' if self.witch_has_poison else '已经用过'}毒药。"
                obs[aid] = (
                    f"女巫阶段。你的编号是 {self.pub(aid)}。{killed_info}"
                    f"{save_info}{poison_info}"
                    f"可选操作：save（救人）、poison(target)（毒人，target=player_x）、connection（跳过）。"
                )
            else:
                obs[aid] = "女巫阶段，请等待。请调用 connection。"
        return obs

    def _obs_night_seer(self) -> dict[str, Any]:
        obs: dict[str, Any] = {}
        alive_list = ", ".join(self.pub(a) for a in self.alive_ids() if a != "seer")
        for aid in ALL_AGENT_IDS:
            if not self.alive[aid]:
                obs[aid] = self._dead_obs(aid, "夜晚-预言家阶段")
            elif aid == "seer" and self.alive.get("seer", False):
                obs[aid] = (
                    f"预言家阶段。你的编号是 {self.pub(aid)}。"
                    f"可查验的存活玩家编号：{alive_list}。"
                    f"请调用 check(target) 查验一名玩家（target=player_x）。"
                )
            else:
                obs[aid] = "预言家阶段，请等待。请调用 connection。"
        return obs

    def _obs_day_announce(self) -> dict[str, Any]:
        obs: dict[str, Any] = {}
        if self.night_deaths:
            death_names = "、".join(self.pub(d) for d in self.night_deaths)
            msg = f"天亮了。昨晚死亡的玩家：{death_names}。请调用 connection。"
        else:
            msg = "天亮了。昨晚是平安夜，无人死亡。请调用 connection。"
        for aid in ALL_AGENT_IDS:
            if not self.alive[aid]:
                obs[aid] = self._dead_obs(aid, "白天-公布信息")
            else:
                obs[aid] = msg
        return obs

    def _obs_day_speak(self) -> dict[str, Any]:
        obs: dict[str, Any] = {}
        if self.speak_index >= len(self.speak_order):
            for aid in ALL_AGENT_IDS:
                obs[aid] = "发言阶段结束。请调用 connection。"
            return obs

        speaker = self.speak_order[self.speak_index]
        history = ""
        if self.speeches:
            history = "已有发言：\n" + "\n".join(
                f"  {self.pub(s)}: {t}" for s, t in self.speeches.items()
            ) + "\n"

        for aid in ALL_AGENT_IDS:
            if not self.alive[aid]:
                obs[aid] = self._dead_obs(aid, "白天-发言阶段")
            elif aid == speaker:
                obs[aid] = (
                    f"白天发言阶段，轮到你（{self.pub(aid)}）发言。\n"
                    f"{history}"
                    f"请调用 speak(text) 发表你的看法。"
                )
            else:
                obs[aid] = (
                    f"白天发言阶段，{self.pub(speaker)} 正在发言，请等待。\n"
                    f"{history}"
                    f"请调用 connection。"
                )
        return obs

    def _obs_day_vote(self) -> dict[str, Any]:
        obs: dict[str, Any] = {}
        alive = self.alive_ids()
        candidates = ", ".join(self.pub(a) for a in alive)
        already_voted = [a for a in alive if self.votes.get(a) is not None]
        first_day_vote = self._is_first_day_vote_round()
        final_round = self.vote_round >= self.vote_max_rounds

        prev_info = ""
        if already_voted:
            prev_info = "已投票：" + ", ".join(
                f"{self.pub(a)}->{self.pub(self.votes[a])}"
                for a in already_voted
            ) + "。"

        for aid in ALL_AGENT_IDS:
            if not self.alive[aid]:
                obs[aid] = self._dead_obs(aid, "白天-投票阶段")
            else:
                has_voted = self.votes.get(aid) is not None
                must_vote = (
                    final_round
                    and not first_day_vote
                    and not has_voted
                )
                force_hint = "【你必须在本轮投票！】" if must_vote else ""
                action_hint = (
                    "你已投过票；如需改票请再次调用 vote(target)，不改则 connection。"
                    if has_voted
                    else (
                        "你尚未投票，本轮必须提交有效 vote(target)"
                        "（target=player_x，且必须是其他存活玩家）。"
                        if must_vote
                        else (
                            "你尚未投票；首个白天第3轮也可继续 connection()，"
                            "也可 vote(target)（target=player_x）。"
                            if final_round and first_day_vote
                            else "你尚未投票，可调用 vote(target)（target=player_x）或 connection 暂时跳过。"
                        )
                    )
                )
                final_rule_hint = (
                    f"（首个白天信息较少，第{self.vote_max_rounds}轮也可不投；无效 vote 不计票）"
                    if first_day_vote
                    else (
                        f"（从第2天起第{self.vote_max_rounds}轮未形成有效票者必须提交有效 vote；"
                        "无效 vote 视为未投并判错）"
                    )
                )
                obs[aid] = (
                    f"投票阶段第{self.vote_round}/{self.vote_max_rounds}轮。"
                    f"候选人：{candidates}。{prev_info}{force_hint}"
                    f"{action_hint}"
                    f"{final_rule_hint}"
                )
        return obs

    def _obs_day_last_words(self) -> dict[str, Any]:
        obs: dict[str, Any] = {}
        target = self.last_words_target
        for aid in ALL_AGENT_IDS:
            if not self.alive[aid] and aid != target:
                obs[aid] = self._dead_obs(aid, "白天-遗言阶段")
            elif aid == target:
                obs[aid] = (
                    f"你（{self.pub(aid)}）被投票淘汰了。"
                    f"请调用 speak(text) 发表遗言。"
                )
            else:
                obs[aid] = f"{self.pub(target)} 正在发表遗言，请等待。请调用 connection。"
        return obs

    def _terminal_obs(self, aid: str) -> str:
        if self.winner == "good":
            return f"游戏结束！好人阵营获胜。你的身份是{self.role_name(aid)}，编号是 {self.pub(aid)}。"
        elif self.winner == "wolf":
            return f"游戏结束！狼人阵营获胜。你的身份是{self.role_name(aid)}，编号是 {self.pub(aid)}。"
        return f"游戏异常结束：{self.error_reason or 'unknown'}"

    # ── action validation ────────────────────────────────────────────

    def _validate_actions(self, action_dict: dict[str, Any]) -> Optional[str]:
        """Return error string if actions are invalid, else None."""
        for aid in ALL_AGENT_IDS:
            act = action_dict.get(aid)
            if act is None:
                return f"{aid} 未提交动作"
            if not isinstance(act, dict):
                return f"{aid} 动作格式错误（应为 dict）"

            action_name = act.get("action", "")
            is_dead = not self.alive[aid]
            is_last_words_speaker = (
                self.phase == Phase.DAY_LAST_WORDS and aid == self.last_words_target
            )

            # 出局玩家只能 connection，但遗言阶段被淘汰者可 speak 发表遗言
            if is_dead and action_name != "connection":
                if not is_last_words_speaker:
                    return f"{aid} 已出局但调用了 {action_name}（应为 connection）"

            if not is_dead or is_last_words_speaker:
                err = self._validate_phase_action(aid, action_name)
                if err:
                    return err

                # Rule refinement:
                # From day 2 onward, in the final vote round, a player without an
                # existing valid vote must submit a *valid* vote target.
                if (
                    self.phase == Phase.DAY_VOTE
                    and self.vote_round >= self.vote_max_rounds
                    and not self._is_first_day_vote_round()
                    and self.votes.get(aid) is None
                    and action_name == "vote"
                    and self._resolve_valid_vote_target(aid, act) is None
                ):
                    return (
                        f"第{self.vote_max_rounds}轮投票，{aid} 必须提交有效 vote(target)，"
                        "target 必须是其他存活玩家"
                    )
        return None

    def _validate_phase_action(self, aid: str, action_name: str) -> Optional[str]:
        """Validate that *aid* may use *action_name* in the current phase."""
        phase = self.phase

        if phase == Phase.SYNC:
            if action_name != "connection":
                return f"{aid} 在游戏同步阶段只能调用 connection，实际调用了 {action_name}"

        elif phase == Phase.NIGHT_WOLF:
            if aid in WOLF_IDS:
                if action_name not in ("kill", "connection"):
                    return f"{aid}(狼人) 夜晚狼人阶段不可调用 {action_name}"
            else:
                if action_name != "connection":
                    return f"{aid} 在狼人阶段只能调用 connection，实际调用了 {action_name}"

        elif phase == Phase.NIGHT_WITCH:
            if aid == "witch":
                if action_name not in ("save", "poison", "connection"):
                    return f"女巫阶段不可调用 {action_name}"
                if action_name == "save" and not self.witch_has_save:
                    return "女巫已经用过解药"
                if action_name == "poison" and not self.witch_has_poison:
                    return "女巫已经用过毒药"
            else:
                if action_name != "connection":
                    return f"{aid} 在女巫阶段只能调用 connection"

        elif phase == Phase.NIGHT_SEER:
            if aid == "seer":
                if action_name not in ("check", "connection"):
                    return f"预言家阶段不可调用 {action_name}"
            else:
                if action_name != "connection":
                    return f"{aid} 在预言家阶段只能调用 connection"

        elif phase == Phase.DAY_ANNOUNCE:
            if action_name != "connection":
                return f"{aid} 在公布信息阶段只能调用 connection"

        elif phase == Phase.DAY_SPEAK:
            speaker = (
                self.speak_order[self.speak_index]
                if self.speak_index < len(self.speak_order)
                else None
            )
            if aid == speaker:
                if action_name not in ("speak", "connection"):
                    return f"发言者 {aid} 只能调用 speak 或 connection"
            else:
                if action_name != "connection":
                    return f"{aid} 不是当前发言者，只能调用 connection"

        elif phase == Phase.DAY_VOTE:
            if action_name not in ("vote", "connection"):
                return f"投票阶段 {aid} 只能调用 vote 或 connection"
            if (
                action_name == "connection"
                and self.vote_round >= self.vote_max_rounds
                and self.votes.get(aid) is None
                and not self._is_first_day_vote_round()
            ):
                return (
                    f"第{self.vote_max_rounds}轮投票，{aid} 尚未投票，不能跳过"
                )

        elif phase == Phase.DAY_LAST_WORDS:
            if aid == self.last_words_target:
                if action_name not in ("speak", "connection"):
                    return f"遗言阶段 {aid} 只能调用 speak 或 connection"
            else:
                if action_name != "connection":
                    return f"{aid} 在遗言阶段只能调用 connection"

        return None

    # ── action handlers ──────────────────────────────────────────────

    def _apply_sync(self, action_dict: dict[str, Any]) -> None:
        """SYNC：所有人 connection 后，进入 NIGHT_WOLF 阶段。"""
        self.phase = Phase.NIGHT_WOLF

    def _apply_night_wolf(self, action_dict: dict[str, Any]) -> None:
        targets: list[str] = []
        for wid in self.alive_wolves():
            act = action_dict.get(wid, {})
            if act.get("action") == "kill":
                t_public = str(act.get("target", ""))
                t = self.resolve_target_public(t_public)
                if t in self.alive_ids() and t not in WOLF_IDS:
                    targets.append(t)

        if targets:
            self.wolf_kill_target = self.rng.choice(targets)
        else:
            # 狼人阶段至少一名存活狼人必须提交有效 kill，否则判错终止
            self.error_reason = "狼人阶段未提交有效 kill 目标（存活狼人应调用 kill(target)）"
            self._end_game(None)
            return
        self.game_log.append(
            f"[夜{self.round_num}] 狼人决定杀害 {self.pub(self.wolf_kill_target)}"
        )
        self.phase = Phase.NIGHT_WITCH

    def _apply_night_witch(self, action_dict: dict[str, Any]) -> None:
        self.witch_saved = False
        self.witch_poison_target = None

        if self.alive.get("witch"):
            act = action_dict.get("witch", {})
            action_name = act.get("action", "")
            if action_name == "save" and self.witch_has_save and self.wolf_kill_target:
                self.witch_saved = True
                self.witch_has_save = False
                self.game_log.append(f"[夜{self.round_num}] 女巫使用解药救了 {self.pub(self.wolf_kill_target)}")
            elif action_name == "poison" and self.witch_has_poison:
                target_public = str(act.get("target", ""))
                target = self.resolve_target_public(target_public)
                if target in self.alive_ids() and target != "witch":
                    self.witch_poison_target = target
                    self.witch_has_poison = False
                    self.game_log.append(f"[夜{self.round_num}] 女巫毒杀了 {self.pub(target)}")

        self.phase = Phase.NIGHT_SEER

    def _apply_night_seer(self, action_dict: dict[str, Any]) -> None:
        self.seer_check_target = None
        self.seer_check_result = None

        if self.alive.get("seer"):
            act = action_dict.get("seer", {})
            if act.get("action") == "check":
                target_public = str(act.get("target", ""))
                target = self.resolve_target_public(target_public)
                if target in ALL_AGENT_IDS and target != "seer":
                    self.seer_check_target = target
                    is_wolf = self.roles.get(target) == "wolf"
                    self.seer_check_result = (
                        f"{self.pub(target)} 的身份是：{'狼人' if is_wolf else '好人'}。"
                    )
                    self.game_log.append(
                        f"[夜{self.round_num}] 预言家查验了 {self.pub(target)}，"
                        f"结果：{'狼人' if is_wolf else '好人'}"
                    )

        self._resolve_night()
        self.phase = Phase.DAY_ANNOUNCE

    def _resolve_night(self) -> None:
        self.night_deaths = []

        if self.wolf_kill_target and not self.witch_saved:
            if self.alive.get(self.wolf_kill_target, False):
                self.alive[self.wolf_kill_target] = False
                self.night_deaths.append(self.wolf_kill_target)
                self.game_log.append(
                    f"[夜{self.round_num}] {self.pub(self.wolf_kill_target)} 死亡（被狼人杀害）"
                )

        if self.witch_poison_target:
            if self.alive.get(self.witch_poison_target, False):
                self.alive[self.witch_poison_target] = False
                self.night_deaths.append(self.witch_poison_target)
                self.game_log.append(
                    f"[夜{self.round_num}] {self.pub(self.witch_poison_target)} 死亡（被女巫毒杀）"
                )

        self.wolf_kill_target = None
        self.witch_saved = False
        self.witch_poison_target = None

    def _apply_day_announce(self, action_dict: dict[str, Any]) -> None:
        self.speak_order = self.alive_ids()
        self.rng.shuffle(self.speak_order)
        self.speak_index = 0
        self.speeches = {}
        self.phase = Phase.DAY_SPEAK

    def _apply_day_speak(self, action_dict: dict[str, Any]) -> None:
        if self.speak_index < len(self.speak_order):
            speaker = self.speak_order[self.speak_index]
            act = action_dict.get(speaker, {})
            if act.get("action") == "speak":
                text = str(act.get("text", ""))[:500]
                self.speeches[speaker] = text
                self.game_log.append(
                    f"[日{self.round_num}] {self.pub(speaker)} 发言: {text[:100]}"
                )
            self.speak_index += 1

        if self.speak_index >= len(self.speak_order):
            self.vote_round = 1
            self.votes = {}
            self.vote_eliminated = None
            self.phase = Phase.DAY_VOTE

    def _apply_day_vote(self, action_dict: dict[str, Any]) -> None:
        for aid in self.alive_ids():
            act = action_dict.get(aid, {})
            if act.get("action") == "vote":
                target = self._resolve_valid_vote_target(aid, act)
                if target is not None:
                    # Allow vote updates across rounds: later valid votes override earlier ones.
                    self.votes[aid] = target

        all_voted = all(
            self.votes.get(aid) is not None for aid in self.alive_ids()
        )

        if all_voted or self.vote_round >= self.vote_max_rounds:
            self._resolve_votes()
        else:
            self.vote_round += 1

    def _resolve_votes(self) -> None:
        tally: dict[str, int] = {}
        for voter, target in self.votes.items():
            if target and self.alive.get(target, False):
                tally[target] = tally.get(target, 0) + 1

        if tally:
            max_count = max(tally.values())
            top = [t for t, c in tally.items() if c == max_count]
            eliminated = self.rng.choice(top)
            self.vote_eliminated = eliminated
            self.alive[eliminated] = False
            self.last_words_target = eliminated
            self.game_log.append(
                f"[日{self.round_num}] 投票结果：{self.pub(eliminated)} 被淘汰 "
                f"(得票{max_count})"
            )
            self.phase = Phase.DAY_LAST_WORDS
        else:
            self.game_log.append(f"[日{self.round_num}] 投票无结果，无人淘汰")
            self.last_words_target = None
            self._advance_to_next_round()

    def _apply_day_last_words(self, action_dict: dict[str, Any]) -> None:
        if self.last_words_target:
            act = action_dict.get(self.last_words_target, {})
            if act.get("action") == "speak":
                text = str(act.get("text", ""))[:500]
                self.game_log.append(
                    f"[日{self.round_num}] {self.pub(self.last_words_target)} 遗言: {text[:100]}"
                )
        self._advance_to_next_round()

    def _advance_to_next_round(self) -> None:
        if not self._check_game_over():
            self.round_num += 1
            if self.round_num > self.max_rounds:
                self._end_game("wolf")
            else:
                self.phase = Phase.NIGHT_WOLF

    # ── game-over check ──────────────────────────────────────────────

    def _check_game_over(self) -> bool:
        wolves = len(self.alive_wolves())
        good = len(self.alive_good())

        if wolves == 0:
            self._end_game("good")
            return True
        if wolves >= good:
            self._end_game("wolf")
            return True
        return False

    def _end_game(self, winner: Optional[str]) -> None:
        self.winner = winner
        self.phase = Phase.GAME_OVER
        if winner:
            self.game_log.append(
                f"=== 游戏结束，{'好人' if winner == 'good' else '狼人'}阵营获胜 ==="
            )

    # ── diagnostics ──────────────────────────────────────────────────

    def build_output_data(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "rounds": self.round_num,
            "steps": self.step_count,
            "alive": {aid: self.alive[aid] for aid in ALL_AGENT_IDS},
            "roles": self.roles,
            "public_id_by_agent": self.public_id_by_agent,
            "game_log": self.game_log[-50:],
            "error": self.error_reason,
        }

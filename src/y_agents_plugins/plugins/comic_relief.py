from __future__ import annotations

import re
from typing import Any

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec, PostRecord, UserRecord
from y_agents_plugins.plugins.base import BaseAgentPlugin


class ComicReliefAgent(BaseAgentPlugin):
    """Humor-oriented agent that replies to or riffs on recent user content."""

    agent_type = "comic_relief"
    _POST_SYSTEM_PROMPT = (
        "You are a comic relief agent in a social simulation. "
        "Write one short public post that tags the target user, references their recent content indirectly, "
        "and adds a playful joke related to the topic. "
        "Keep the humor light, clever, and non-abusive. Avoid insults, harassment, slurs, threats, sexual content, "
        "or humiliation. The goal is to ease tension, not escalate it."
    )
    _COMMENT_SYSTEM_PROMPT = (
        "You are a comic relief agent in a social simulation. "
        "Write one short reply comment that tags the target user and riffs jokingly on their post while staying on topic. "
        "Keep the humor light, clever, and non-abusive. Avoid insults, harassment, slurs, threats, sexual content, "
        "or humiliation. The goal is to ease tension, not escalate it."
    )
    _DEFAULT_STYLES = ["dad_jokes"]
    _PLUGIN_USER_TYPES = {
        "hello_world",
        "moderator",
        "propaganda",
        "master_of_puppets",
        "mop_puppet",
        "stress_attacker",
        "comic_relief",
    }

    def on_tick(self, context: AgentContext, agent: AgentSpec) -> list[AgentAction]:
        target_post = self._select_target_post(context=context, agent=agent)
        if target_post is None:
            return [self._read_action(context, agent)]
        target_user = self._user_by_id(target_post.author_id, users=context.users)
        if self._delivery_mode(agent, context.current_round.id) == "comment":
            return [
                self._read_action(context, agent),
                AgentAction(
                    agent_type=self.agent_type,
                    action_type="CREATE_COMMENT",
                    payload={
                        "parent_post_id": target_post.id,
                        "thread_id": target_post.thread_id or target_post.id,
                        "text": self._build_comment_text(
                            agent=agent,
                            target_user=target_user,
                            target_post=target_post,
                        ),
                        "stress_reward": {
                            "tone": "supportive",
                            "action": "comment:supportive",
                        },
                    },
                ),
            ]
        return [
            self._read_action(context, agent),
            AgentAction(
                agent_type=self.agent_type,
                action_type="CREATE_POST",
                payload={
                    "text": self._build_post_text(
                        agent=agent,
                        target_user=target_user,
                        target_post=target_post,
                    ),
                        "stress_reward": {
                            "tone": "supportive",
                            "action": "post:supportive",
                            "target_user_id": target_user.id,
                        },
                    },
                ),
        ]

    def _select_target_post(
        self,
        *,
        context: AgentContext,
        agent: AgentSpec,
    ) -> PostRecord | None:
        actor_user_id = None
        if context.connection is not None:
            try:
                actor_user_id = self.database.get_user_id(context.connection, agent.username)
            except Exception:
                actor_user_id = None
        lookback_rounds = max(1, int((agent.parameters or {}).get("post_lookback_rounds") or self.settings.get("post_lookback_rounds") or 24))
        min_round = context.current_round.ordinal - lookback_rounds
        candidates = []
        for post in context.recent_posts:
            if post.round_ordinal < min_round:
                continue
            if int(post.is_moderation_comment or 0):
                continue
            if actor_user_id is not None and str(post.author_id) == str(actor_user_id):
                continue
            user = self._safe_user_by_id(post.author_id, users=context.users)
            if user is None:
                continue
            user_type = str(user.user_type or "").strip().lower()
            if user_type in self._PLUGIN_USER_TYPES:
                continue
            candidates.append(post)
        if not candidates:
            return None
        candidates.sort(key=lambda post: (post.round_ordinal, str(post.id)), reverse=True)
        return candidates[0]

    def _build_post_text(
        self,
        *,
        agent: AgentSpec,
        target_user: UserRecord,
        target_post: PostRecord,
    ) -> str:
        if self.llm is None or not getattr(self.llm, "is_available", False):
            return self._normalize_target_tag(
                f"@{target_user.username} I read that and my inner dad-joke machine immediately filed a bug report.",
                target_user.username,
            )
        system_prompt = str(
            self._resolved_settings(agent).get("opening_llm_prompt_override")
            or self._POST_SYSTEM_PROMPT
        ).strip()
        user_prompt = (
            f"Comic relief styles: {', '.join(self._humor_styles(agent))}\n"
            f"Target user profile: {target_user.profile}\n"
            f"Original post: {target_post.text}\n"
            f"Write one short humorous post that starts with '@{target_user.username} '. "
            "Make it clearly related to the original post, playful, and safe for a public feed. "
            "Return only the post text."
        )
        text = self.llm.invoke_text(system_prompt=system_prompt, user_prompt=user_prompt).strip()
        return self._normalize_target_tag(text, target_user.username)

    def _build_comment_text(
        self,
        *,
        agent: AgentSpec,
        target_user: UserRecord,
        target_post: PostRecord,
    ) -> str:
        if self.llm is None or not getattr(self.llm, "is_available", False):
            return self._normalize_target_tag(
                f"@{target_user.username} That post has strong \"debugged at 2am\" energy, in the funniest possible way.",
                target_user.username,
            )
        system_prompt = str(
            self._resolved_settings(agent).get("reply_llm_prompt_override")
            or self._COMMENT_SYSTEM_PROMPT
        ).strip()
        user_prompt = (
            f"Comic relief styles: {', '.join(self._humor_styles(agent))}\n"
            f"Target user profile: {target_user.profile}\n"
            f"Original post: {target_post.text}\n"
            f"Write one short humorous reply that starts with '@{target_user.username} '. "
            "Keep it related to the original post, playful, and safe for a public thread. "
            "Return only the reply text."
        )
        text = self.llm.invoke_text(system_prompt=system_prompt, user_prompt=user_prompt).strip()
        return self._normalize_target_tag(text, target_user.username)

    def _read_action(self, context: AgentContext, agent: AgentSpec) -> AgentAction:
        return AgentAction(
            agent_type=self.agent_type,
            action_type="READ",
            payload={
                "agent_username": agent.username,
                "agent_name": agent.name,
                "round_id": context.current_round.id,
            },
        )

    def _delivery_mode(self, agent: AgentSpec, round_id) -> str:
        mode = str(
            self._resolved_settings(agent).get("delivery_mode")
            or "alternate"
        ).strip().lower()
        if mode == "post_only":
            return "post"
        if mode == "comment_only":
            return "comment"
        return "post" if (self._round_parity(round_id) % 2) else "comment"

    def _humor_styles(self, agent: AgentSpec) -> list[str]:
        value = self._resolved_settings(agent).get("humor_styles")
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return cleaned or list(self._DEFAULT_STYLES)
        return list(self._DEFAULT_STYLES)

    def _resolved_settings(self, agent: AgentSpec | None = None) -> dict[str, Any]:
        settings = dict(self.settings)
        if agent is not None:
            settings.update(agent.parameters or {})
        return settings

    @staticmethod
    def _sanitize_generated_social_text(text: str) -> str:
        cleaned = str(text or "").strip()
        cleaned = re.sub(
            r'^\s*(?:here(?:’|\'|)s|here is)\s+(?:a\s+)?(?:possible\s+)?(?:post|reply|comment)\s*:\s*',
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
            cleaned = cleaned[1:-1].strip()
        return cleaned

    @classmethod
    def _normalize_target_tag(cls, text: str, username: str) -> str:
        cleaned = cls._sanitize_generated_social_text(text)
        direct_tag = re.compile(rf"@{re.escape(username)}\b", re.IGNORECASE)
        if not direct_tag.search(cleaned):
            cleaned = f"@{username} {cleaned}".strip()
        return cleaned

    @staticmethod
    def _safe_user_by_id(user_id, *, users: tuple[UserRecord, ...]) -> UserRecord | None:
        for user in users:
            if str(user.id) == str(user_id):
                return user
        return None

    def _user_by_id(self, user_id, *, users: tuple[UserRecord, ...]) -> UserRecord:
        user = self._safe_user_by_id(user_id, users=users)
        if user is None:
            raise RuntimeError(f"User '{user_id}' not found in AgentContext.users")
        return user

    @staticmethod
    def _round_parity(round_id) -> int:
        try:
            return int(round_id)
        except Exception:
            return sum(ord(ch) for ch in str(round_id or ""))

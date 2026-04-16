# Stress Attacker

Stress Attacker is a bounded adversarial test agent used to exercise stress, churn, and mitigation pipelines without introducing a full harassment actor. It does not maintain its own long conversational strategy. Instead, it picks one viable target at a time, applies a short burst of negative pressure, then cools down before choosing again.

The agent is only meaningful in experiments where the `stress_reward` pipeline is active. Its whole purpose is to generate events that increase the selected user’s stress through the same experiment mechanisms already used by the main clients. Depending on configuration, those events may remain synthetic or may include a real LLM-generated critical reply.

Unlike Master of Puppets, Stress Attacker does not create real puppet accounts. The coordinated behavior is represented numerically through `source_count`, burst volume, and report volume. That keeps the agent useful as a mitigation benchmark while avoiding the overhead of managing a separate puppet population.

## Typical Behavior

Suppose you configure the agent to target younger users with a specific political leaning, keep pressure on one victim for `4` rounds, and then wait `8` rounds before moving on.

During an active slot, the agent may:

1. choose a target whose profile matches the configured demographic filters,
2. inspect the target’s recent posts inside the configured lookback window,
3. apply a synthetic dislike burst against one recent post,
4. add either a synthetic critical-comment event or a real critical reply comment,
5. insert a synthetic report burst against the same post,
6. store campaign state so the same target is kept for the configured burst duration.

The result is not random noise. It is a reproducible short campaign whose downstream effects can be inspected through the normal experiment tables and, when enabled, through `stress_reward`.

## Parameters

The target itself is defined at ad hoc client creation time. `target_filters` lets YSocial build one or more demographic rules against the experiment population, such as political leaning, language, age bounds, profession, or custom features. The agent scores candidates partly by recent posting activity, so inactive users are less likely to be selected.

`burst_rounds` and `cooldown_rounds` define the campaign rhythm. `burst_rounds` says how long the same target remains active. `cooldown_rounds` says how long the attacker waits before starting a new campaign. `post_lookback_rounds` limits how far back the agent searches for candidate posts, while `source_count` defines the synthetic size of the coordinated pressure represented in each burst.

Three strategy groups can then be enabled independently. `negative_reactions_enabled` and `reaction_burst_volume` control synthetic dislike pressure. `critical_comment_enabled` controls comment pressure, and `critical_comment_mode` decides whether that pressure is a synthetic stress event or a real reply comment. When the mode is `synthetic`, `critical_comment_text` defines the comment body and the target handle is automatically prepended. When the mode is `llm`, the agent uses the configured model and the optional full `llm_prompt_override` to generate one short critical reply tied to the target’s post.

Finally, `report_burst_enabled` and `report_burst_volume` control synthetic reporting pressure. This writes report-like events and matching stress updates against the selected target’s recent post.

## When To Use It

Use Stress Attacker when you need a repeatable adverse-pressure baseline for testing stress accumulation, churn probability, moderation defenses, or mitigation policies. It is the better choice when the question is not whether content becomes visible, but whether a targeted sequence of negative interactions changes a user’s measured platform experience.

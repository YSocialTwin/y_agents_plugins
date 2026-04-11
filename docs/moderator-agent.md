# Moderator Agent

The Moderator agent is the enforcement actor in the plugin catalog. Its job is to watch recent content, decide whether intervention is warranted, and record the result in a way that is visible both to the offending user and to the rest of the simulation.

Unlike the Hello World agent, the Moderator is stateful in a meaningful way. It reads reports, toxicity annotations, prior infractions, and the current round. It may also create and maintain plugin-owned tables for moderation escalation, such as temporary shadow bans and permanent bans. The agent is therefore less about generating conversation and more about shaping the boundaries of what remains visible and acceptable on the platform.

In its simplest configuration, the Moderator applies a standard notice to problematic posts. In its more advanced configuration, it uses an LLM to produce a more tailored moderation message. Either way, the core pattern is the same: identify a candidate, issue a moderation notice, comment publicly on the moderated content, and mark the content as already handled.

## Typical Behavior

Suppose a user publishes a post that has already been reported and whose toxicity annotation crosses the configured threshold. During the Moderator’s next active slot, it may:

1. select that post as a candidate,
2. create a system message addressed to the author,
3. write the same moderation notice as a visible reply beneath the offending content,
4. mark the post as moderated so it is not selected again.

If shadow ban is enabled and the same user accumulates enough recent infractions, the Moderator can escalate. At that point the user may keep posting, but their content disappears from recommendations and mention-reply paths while the ban is active. If permanent ban is enabled, the Moderator can go one step further and mark the user as left from the platform after one more infraction beyond the warning threshold.

## Parameters

The most important setting is `moderation_action_type`. With `one-fits-all`, the agent uses a standard warning style. With `personalized`, the agent relies on the configured LLM to generate a user-specific notice. The latter is useful when you want moderation to feel more contextual, but it also means the quality of the output depends on the model you provide.

`toxicity_threshold` determines how aggressive the Moderator is when inspecting annotated content. A lower threshold means more interventions. A higher one means the Moderator will mostly ignore borderline material and step in only for clearly problematic posts.

`moderation_time_span` controls how long the generated system message remains active in `sys_messages`. `candidate_window_rounds` controls how far back the Moderator looks when searching for recent unmoderated content.

If you enable shadow banning, three more parameters become relevant. `shadow_ban_infraction_window_rounds` defines the lookback window used to count prior moderation events. `shadow_ban_n_infraction` sets the threshold, and `shadow_ban_duration_rounds` defines how long the temporary visibility suppression lasts.

If you enable permanent banning, `ban_infraction_window_rounds` and `ban_n_infraction` define the warning and escalation path. Once the threshold is reached, the user is warned that the next infraction inside the same window will result in a permanent ban. When that extra infraction occurs, the Moderator updates `user_mgmt.left_on` and records the event in the plugin-owned `banned` table.

## When To Use It

Use the Moderator when you need the simulation to model platform governance rather than just organic interaction. It is especially useful if you already enable toxicity annotation or user reporting and you want those signals to produce visible downstream consequences.

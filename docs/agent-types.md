# Available Agent Types

This page documents the built-in ad hoc agent types shipped in `y_agents_plugins`.

Each client process binds to exactly one `agent_type`. The packaged catalog for YSocial/YWeb lives in `meta/registry.json`, while the Python implementations live under `src/y_agents_plugins/plugins/`.

## Shared Core Parameters

All built-in agent types expose these base population parameters:

- `name`: human-readable agent name stored in the experiment population
- `activity_profile`: name of a `simulation.activity_profiles` entry from the client configuration
- `daily_budget`: numeric daily budget persisted in the experiment population

Some agent types also require extra client-level settings when the ad hoc client is created in YSocial.

## Hello World Agent

- `agent_type`: `hello_world`
- Goal: publish a simple fixed message during each active round
- LLM required: no

### Behavior

On every active tick, the agent creates one post containing a configured literal text. The default text is `HELLO WORLD`.

### Parameters

- `post_text`:
  - Type: string
  - Default: `HELLO WORLD`
  - Meaning: the exact text posted on each active round

## Moderator Agent

- `agent_type`: `moderator`
- Goal: detect problematic content and apply moderation interventions
- LLM required: yes for `personalized`, no for `one-fits-all`

### Behavior

During active rounds, the moderator scans recent unmoderated content. It prioritizes reported items and highly toxic items, then:

- creates a moderation notice in `sys_messages`
- adds a visible moderation comment below the offending content
- marks the post as moderated

Optional escalation modes are also supported:

- shadow ban
- permanent ban

The moderator autonomously creates the plugin-owned moderation tables it needs if they are not already present.

### Parameters

- `toxicity_threshold`:
  - Type: float
  - Default: `0.8`
  - Meaning: minimum toxicity score that makes content eligible for moderation
- `moderation_time_span`:
  - Type: integer
  - Default: `24`
  - Meaning: number of rounds the moderation system message stays active
- `moderation_action_type`:
  - Type: enum `one-fits-all | personalized`
  - Default: `one-fits-all`
  - Meaning: whether notices are standardized or LLM-personalized
- `candidate_window_rounds`:
  - Type: integer
  - Default: `1`
  - Meaning: lookback window used to collect recent moderation candidates

### Shadow Ban Parameters

- `shadow_ban_enabled`:
  - Type: enum `disabled | enabled`
  - Default: `disabled`
- `shadow_ban_infraction_window_rounds`:
  - Type: integer
  - Default: `24`
  - Meaning: lookback window used to count prior infractions
- `shadow_ban_n_infraction`:
  - Type: integer
  - Default: `3`
  - Meaning: number of infractions needed to trigger a shadow ban
- `shadow_ban_duration_rounds`:
  - Type: integer
  - Default: `24`
  - Meaning: duration of the shadow ban in rounds

### Permanent Ban Parameters

- `ban_enabled`:
  - Type: enum `disabled | enabled`
  - Default: `disabled`
- `ban_infraction_window_rounds`:
  - Type: integer
  - Default: `24`
  - Meaning: lookback window used to count infractions for permanent-ban escalation
- `ban_n_infraction`:
  - Type: integer
  - Default: `3`
  - Meaning: warning threshold; the next infraction within the same window causes a permanent ban

## Propaganda Agent

- `agent_type`: `propaganda`
- Goal: shift selected users toward a target opinion on configured opinion-dynamics topics
- LLM required: yes
- Requires opinion dynamics: yes

### Behavior

The propaganda agent:

- selects a target user based on `agent_opinion`
- opens a tagged persuasion thread on a configured topic
- replies in-thread when the target user answers
- measures observed opinion change after replies
- stops once the target is close enough to the campaign goal, or once the conversation-round limit is reached

It also persists campaign progress into `propaganda_activity`.

### Core Parameters

- `epsilon`:
  - Type: float
  - Default: defined in the client form
  - Meaning: tolerance used to decide whether the target reached the desired opinion
- `max_interaction_rounds`:
  - Type: integer
  - Default: defined in the client form
  - Meaning: maximum number of follow-up interaction rounds per persuasion thread
- `max_concurrent_targets`:
  - Type: integer
  - Default: defined in the client form
  - Meaning: maximum number of target users handled at the same time

### Client-Level Campaign Parameters

Configured in YSocial when the ad hoc client is created:

- campaign topic
- opinion propaganda target
- target agent opinion group
- optional political leaning filter
- optional age-class filter

The topic choices and opinion classes are taken from the experiment and dashboard databases.

## Master of Puppets Agent

- `agent_type`: `master_of_puppets`
- Goal: coordinate multiple rule-based puppet accounts to amplify selected topics and narratives
- LLM required: yes

### Behavior

The Master of Puppets agent is an orchestrator. It does not directly behave like a normal conversational actor. Instead, it:

- creates and maintains a fixed number of puppet accounts
- replaces puppets that become banned
- generates a daily schedule for each puppet
- distributes the total daily budget across:
  - posting
  - support / boosting
  - network building
- executes puppet actions through the standard experiment tables

Puppets can:

- publish MoP-generated content
- follow users
- like or share sibling-puppet content

The plugin creates and manages the following coordination tables:

- `mop_registry`
- `puppet_registry`
- `daily_schedules`
- `activity_logs`

### Parameters

- `puppet_count`:
  - Type: integer
  - Meaning: number of active puppet accounts MoP tries to maintain
- `daily_budget`:
  - Type: number
  - Meaning: total daily action budget across all puppets
- `post_budget_percentage`:
  - Type: number
  - Meaning: share of the total daily budget assigned to posting
- `support_budget_percentage`:
  - Type: number
  - Meaning: share of the total daily budget assigned to liking/sharing sibling content
- `network_budget_percentage`:
  - Type: number
  - Meaning: share of the total daily budget assigned to follow actions
- `boost_lookback_hours`:
  - Type: integer
  - Meaning: how far back the agent looks for sibling posts that can be boosted

### Client-Level Campaign Parameters

Configured in YSocial when the ad hoc client is created:

- target topic
- optional opinion target class for that topic

If an opinion class is configured, each puppet is seeded with the corresponding fixed opinion value in `agent_opinion`.

## Implementation Notes

- The runtime executor is responsible for writing posts, comments, reactions, follows, shares, and plugin side effects into the experiment database.
- Plugin agents may create plugin-owned tables when needed, but they must continue to respect the YSocial client/server contract for standard simulation actors.
- YSocial discovers these agent types through `meta/registry.json`, which also drives the dynamic form rendering for ad hoc client creation.

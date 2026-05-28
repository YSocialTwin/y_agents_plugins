# Master of Puppets (MoP)

Master of Puppets is the most orchestration-heavy agent in the package. Instead of behaving as a single social actor, it behaves as a planner that manages a fleet of puppet accounts. The MoP decides what those puppets should do during the day, when they should do it, and how the total budget should be split across posting, boosting, and network growth.

That makes it fundamentally different from Propaganda. Propaganda tries to shift a specific user through a focused conversational thread. MoP is about coordinated amplification. It aims to make a narrative more visible, more socially reinforced, and more likely to spread through repeated low-level actions carried out by multiple managed accounts.

The MoP keeps its own coordination tables. It registers its campaigns in `mop_registry`, tracks the puppet population in `puppet_registry`, writes per-day execution plans into `daily_schedules`, and records the actual side effects in `activity_logs`. Those tables are plugin-owned, and the agent can create them autonomously at startup if they are missing.

## Typical Behavior

Imagine a MoP campaign targeting the topic `Climate`, with two puppet accounts and a daily budget split across posting, support, and network building.

At the beginning of a new day, the MoP checks whether any puppet has been banned. If one disappeared, the orchestrator creates a replacement so the fleet size stays stable.

It then generates a schedule. One puppet may be assigned to publish a topic-relevant post in the morning. Another may be assigned to follow a cluster of users later in the day. Still later, one puppet may like or share a sibling puppet’s earlier post so that the content appears more active and socially validated than it would have otherwise.

The puppets themselves are not doing strategic reasoning. They are workers. When a scheduled time arrives, a puppet executes the assigned action if its local daily allowance still permits it. That is why the MoP is best understood as the “what” and “when” layer, while the puppets handle the “how”.

## Parameters

The most important structural parameter is `puppet_count`, which defines how many active puppet accounts the MoP tries to maintain. If a puppet is banned, the agent replaces it during the next maintenance cycle.

`daily_budget` is the total action capacity for the entire puppet network, not for one puppet. The MoP then divides that total budget according to three percentage parameters: `post_budget_percentage`, `support_budget_percentage`, and `network_budget_percentage`. This gives you a high-level control surface. You do not need to micromanage how many posts each puppet should write. You just tell the orchestrator how aggressive the campaign should be on each front.

`boost_lookback_hours` determines how far back a puppet may look when searching for sibling content to like or share.

Campaign topics are configured from YSocial when the ad hoc client is created. If you also specify an opinion class for a topic, the MoP seeds each puppet with a fixed opinion value on that topic, using the corresponding opinion-group interval from the experiment database. This matters because puppet-authored content can then be aligned with a coherent stance instead of acting as if each puppet had no opinion state.

## What To Expect In The Database

When the MoP is working as intended, you should see four things happen together.

First, the puppet accounts appear in `user_mgmt` and `puppet_registry`. Second, `daily_schedules` gets filled with the current day’s plan. Third, real actions show up in the standard experiment tables such as `post`, `follow`, `reactions`, and `post_topics`. Fourth, the audit trail in `activity_logs` tells you which scheduled actions actually ran and which were skipped.

If a puppet publishes MoP-generated content on a configured topic, that post should also be reflected in `post_topics`. If the campaign specified an opinion class, you should also see the puppet’s fixed opinion in `agent_opinion`.

## When To Use It

Use Master of Puppets when the question is not whether one agent can persuade one user, but whether a coordinated cluster of accounts can shape what becomes visible, repeated, and socially reinforced on the platform.

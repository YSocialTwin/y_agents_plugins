# Comic Relief Agent

Comic Relief is the tension-lowering agent in the plugin catalog. Its job is to look at recent user-generated content, pick a non-plugin author, and respond with a playful post or reply that stays related to the original topic while keeping the tone light.

Unlike Propaganda, Comic Relief is not trying to persuade. Unlike Moderator, it is not trying to enforce norms. Its role is to inject levity into active conversations, always by tagging the target user directly so the humorous intervention is clearly connected to the original content.

The agent requires LLM access because both its standalone posts and its reply comments are generated from the target’s recent content and selected humor styles. When `stress_reward` is enabled for the experiment, the resulting actions are annotated as supportive so they flow through the same pipeline as any other positive interaction.

## Typical Behavior

Imagine a user has just written a serious or slightly tense post about technology policy. During Comic Relief’s next active slot, it may:

1. inspect the most recent eligible post written by a non-plugin user,
2. decide whether this round should produce a tagged post or a tagged reply comment,
3. build a short prompt using the target user profile, the original post, and the selected humor styles,
4. generate one playful line that starts with `@target_username`,
5. publish that joke either as a new post or as an in-thread reply.

If no LLM is available, the agent still falls back to a built-in safe joke pattern so the execution path remains valid.

## Parameters

Comic Relief has both per-agent and per-client settings. At agent creation time, `humor_styles` defines the comedic voice of that specific agent. The built-in catalog includes styles such as `dad_jokes`, `nerdy`, `wordplay`, `dry_wit`, `absurdist`, `wholesome`, `observational`, `pop_culture`, `office_humor`, `science_geek`, `fantasy_gaming`, `history_gags`, `sports_banter`, `food_puns`, `travel_gags`, and `awkward_social`. You can combine more than one style so the generated humor is not locked to a single register.

At ad hoc client creation time, `delivery_mode` controls how the agent publishes. With `alternate`, it switches between tagged posts and reply comments based on the round. With `post_only` or `comment_only`, it stays in a single delivery mode. `post_lookback_rounds` determines how far back the agent can search when looking for a recent post to riff on.

If you need tighter prompt control, the agent exposes two separate full prompt overrides: `opening_llm_prompt_override` for standalone tagged joke posts and `reply_llm_prompt_override` for in-thread comments. Those overrides replace the built-in system prompts entirely.

## When To Use It

Use Comic Relief when you want to study whether humor can soften the tone of an interaction space, create affiliative touchpoints, or provide a positive counterweight to more confrontational actors. It is especially useful in experiments that already track stress and reward, because its supportive outputs can be measured alongside more negative interventions.

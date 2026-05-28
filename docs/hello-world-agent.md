# Hello World Agent

The Hello World agent is the smallest useful plugin in the package. It exists to prove that the ad hoc client runtime is correctly connected to the experiment clock, that the population can be registered, and that posts can be written into the live experiment database without touching the standard YSocial clients.

In practice, it behaves like a metronome. Whenever one of its active rounds arrives, it emits exactly one post and then waits for the next eligible round. There is no memory, no targeting logic, no moderation workflow, and no LLM dependency. That makes it a good choice when you want a predictable baseline or a quick integration check after changing the plugin runtime.

By default, the agent posts the text `HELLO WORLD`. The implementation has been generalized so that the posted text can now be configured. If you leave the parameter unset, the old behavior is preserved exactly.

## Typical Behavior

Imagine an agent called `hello_1` with an `Always On` activity profile. During the simulation it will produce a simple stream of repeated posts such as:

```text
HELLO WORLD
```

If you configure `post_text` as `System check complete`, then the same agent will instead post:

```text
System check complete
```

The point is not realism. The point is deterministic behavior that is easy to verify in logs and in the `post` table.

## Parameters

The agent uses the standard population identity parameters plus one optional behavior parameter.

`post_text` is the only specific setting. It is a plain string, and its default value is `HELLO WORLD`. Whatever value you provide is published literally on each active round.

## When To Use It

Use Hello World when you need a sanity check, a stable fixture for tests, or a visible signal that the plugin client is alive and synchronized with the experiment. If you need the agent to react to users, inspect opinions, or coordinate other accounts, this is the wrong tool.

from __future__ import annotations

import argparse
import json
import logging

from y_agents_plugins.config import AppConfig
from y_agents_plugins.runtime import ClientApp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a YSocial plugin client.")
    parser.add_argument("config", help="Path to the JSON configuration file.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    app = ClientApp(AppConfig.from_file(args.config))
    actions = app.run()
    print(json.dumps([_serialize_action(action) for action in actions], indent=2))


def _serialize_action(action) -> dict:
    return {
        "agent_type": action.agent_type,
        "action_type": action.action_type,
        "payload": action.payload,
    }


if __name__ == "__main__":
    main()

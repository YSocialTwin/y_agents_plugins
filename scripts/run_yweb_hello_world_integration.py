from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
YWEB_ROOT = Path("/Users/rossetti/PycharmProjects/YWeb")
SERVER_ROOT = YWEB_ROOT / "external" / "YServer"
CLIENT_ROOT = YWEB_ROOT / "external" / "YClient"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_server(base_url: str, timeout_seconds: int = 30) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/current_time", timeout=1)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Server at {base_url} did not become ready")


def main() -> int:
    run_id = f"hello_world_{int(time.time())}"
    run_dir = ROOT / "run_outputs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    server_port = free_port()
    base_url = f"http://127.0.0.1:{server_port}"
    database_path = run_dir / "database_server.db"
    prompts_src = CLIENT_ROOT / "config_files" / "prompts.json"
    prompts_dst = run_dir / "prompts.json"
    shutil.copyfile(prompts_src, prompts_dst)

    client_config = {
        "servers": {
            "llm": "http://127.0.0.1:11434/v1",
            "llm_api_key": "NULL",
            "llm_max_tokens": -1,
            "llm_temperature": 1.0,
            "llm_v": "http://127.0.0.1:11434/v1",
            "llm_v_api_key": "NULL",
            "llm_v_max_tokens": 300,
            "llm_v_temperature": 0.5,
            "api": f"{base_url}/",
        },
        "simulation": {
            "name": run_id,
            "client": "YClientBase",
            "days": 10,
            "slots": 24,
            "starting_agents": 10,
            "percentage_new_agents_iteration": 0.0,
            "percentage_removed_agents_iteration": 0.0,
            "hourly_activity": {str(hour): 0.1 for hour in range(24)},
            "actions_likelihood": {
                "post": 1.0,
                "image": 0.0,
                "news": 0.0,
                "comment": 0.0,
                "read": 0.0,
                "share": 0.0,
                "search": 0.0,
                "cast": 0.0,
            },
        },
        "agents": {
            "languages": ["English"],
            "education_levels": ["high school"],
            "max_length_thread_reading": 5,
            "reading_from_follower_ratio": 0.6,
            "political_leanings": ["Independent"],
            "age": {"min": 25, "max": 40},
            "daily_actions": {"min": 1, "max": 1},
            "llm_agents": ["llama3.2:latest"],
            "llm_v_agent": "minicpm-v:latest",
            "n_interests": {"min": 1, "max": 1},
            "round_actions": {"min": 1, "max": 1},
            "nationalities": ["American"],
            "probability_of_daily_follow": 0.0,
            "probability_of_secondary_follow": 0.0,
            "interests": ["testing"],
            "toxicity_levels": ["low"],
            "attention_window": 48,
            "max_replies_per_round": 2,
            "reply_cooldown_rounds": 2,
            "thread_browse_mode": "llm",
            "thread_browse_order": "tree_dfs",
            "thread_browse_max_nodes": 100,
            "thread_browse_chunk_size": 20,
            "thread_browse_top_k": 6,
            "thread_browse_max_llm_steps": 3,
            "thread_browse_snippet_chars": 220,
            "thread_browse_context_window": 30,
            "big_five": {
                "oe": ["inventive/curious"],
                "co": ["efficient/organized"],
                "ex": ["outgoing/energetic"],
                "ag": ["friendly/compassionate"],
                "ne": ["resilient/confident"],
            },
            "memory_enabled": False,
        },
        "posts": {
            "visibility_rounds": 36,
            "emotions": {"joy": None},
        },
    }
    server_config = {
        "name": run_id,
        "host": "127.0.0.1",
        "port": server_port,
        "debug": "False",
        "reset_db": "True",
        "modules": ["news", "voting", "image"],
        "perspective_api": None,
        "toxicity_annotation": False,
        "sentiment_annotation": False,
        "emotion_annotation": False,
        "database_uri": str(database_path),
    }
    plugin_population = {
        "agents": [
            {
                "name": "HelloWorldBot",
                "username": "helloworldbot",
                "email": "helloworldbot@example.org",
                "password": "secret",
                "agent_type": "hello_world",
                "activity_profile": "Always On",
                "daily_budget": 24,
                "language": "English",
            }
        ]
    }
    plugin_config = {
        "database": {
            "sqlite_path": str(database_path),
            "poll_interval_seconds": 0.05,
        },
        "client": {
            "client_id": "hello-world-plugin-client",
            "agent_type": "hello_world",
            "servers": client_config["servers"],
            "simulation": {
                "days": 10,
                "slots": 24,
                "population_json_path": str(run_dir / "hello_world_population.json"),
            },
            "max_ticks": 240,
        },
    }

    (run_dir / "client_config.json").write_text(json.dumps(client_config, indent=2))
    (run_dir / "server_config.json").write_text(json.dumps(server_config, indent=2))
    (run_dir / "hello_world_population.json").write_text(json.dumps(plugin_population, indent=2))
    (run_dir / "plugin_config.json").write_text(json.dumps(plugin_config, indent=2))

    server_log = open(run_dir / "server.stdout.log", "w", encoding="utf-8")
    std_client_log = open(run_dir / "std_client.stdout.log", "w", encoding="utf-8")
    plugin_log = open(run_dir / "plugin_client.stdout.log", "w", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(ROOT / "src"),
            env.get("PYTHONPATH", ""),
        ]
    )

    server_proc = subprocess.Popen(
        [sys.executable, "y_server_run.py", "-c", str(run_dir / "server_config.json")],
        cwd=str(SERVER_ROOT),
        stdout=server_log,
        stderr=subprocess.STDOUT,
        env=env,
    )

    try:
        wait_for_server(base_url)

        plugin_proc = subprocess.Popen(
            [sys.executable, "-m", "y_agents_plugins.cli", str(run_dir / "plugin_config.json")],
            cwd=str(ROOT),
            stdout=plugin_log,
            stderr=subprocess.STDOUT,
            env=env,
        )

        std_client_proc = subprocess.Popen(
            [
                sys.executable,
                "y_client.py",
                "-c",
                str(run_dir / "client_config.json"),
                "-p",
                str(prompts_dst),
                "-o",
                "Admin",
            ],
            cwd=str(CLIENT_ROOT),
            stdout=std_client_log,
            stderr=subprocess.STDOUT,
            env=env,
        )

        std_code = std_client_proc.wait(timeout=1800)
        plugin_code = plugin_proc.wait(timeout=1800)
        if std_code != 0:
            raise RuntimeError(f"Standard client exited with code {std_code}")
        if plugin_code != 0:
            raise RuntimeError(f"Plugin client exited with code {plugin_code}")

        import sqlite3

        connection = sqlite3.connect(database_path)
        hello_posts = connection.execute(
            """
            SELECT COUNT(*)
            FROM post
            JOIN user_mgmt ON user_mgmt.id = post.user_id
            WHERE user_mgmt.username = 'helloworldbot' AND post.tweet = 'HELLO WORLD'
            """
        ).fetchone()[0]
        round_count = connection.execute("SELECT COUNT(*) FROM rounds").fetchone()[0]
        hello_rounds = connection.execute(
            """
            SELECT COUNT(DISTINCT post.round)
            FROM post
            JOIN user_mgmt ON user_mgmt.id = post.user_id
            WHERE user_mgmt.username = 'helloworldbot' AND post.tweet = 'HELLO WORLD'
            """
        ).fetchone()[0]
        connection.close()

        print(
            json.dumps(
                {
                    "run_dir": str(run_dir),
                    "database_path": str(database_path),
                    "hello_world_posts": hello_posts,
                    "distinct_hello_world_rounds": hello_rounds,
                    "total_round_rows": round_count,
                },
                indent=2,
            )
        )

        if hello_posts != 240 or hello_rounds != 240:
            raise RuntimeError(
                f"Expected 240 HELLO WORLD posts across 240 rounds, got posts={hello_posts}, rounds={hello_rounds}"
            )

        return 0
    finally:
        for proc in ("std_client_proc", "plugin_proc", "server_proc"):
            process = locals().get(proc)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except Exception:
                    process.kill()
        server_log.close()
        std_client_log.close()
        plugin_log.close()


if __name__ == "__main__":
    raise SystemExit(main())

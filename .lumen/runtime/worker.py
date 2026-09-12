from app import load_state, seed_demo, autopilot_tick, STATE, DB_STATUS

if __name__ == "__main__":
    loaded = load_state()
    if not loaded or not STATE.get("buyers"):
        seed_demo()
    result = autopilot_tick("worker autónomo")
    print({"result": result, "postgres": DB_STATUS}, flush=True)
    if not result.get("persisted"):
        raise SystemExit(2)

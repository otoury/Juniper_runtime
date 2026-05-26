ESCALATION_POLICY = {

    "CLOUD_FAST": {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "web_search": False,
    },

    "CLOUD_DEEP": {
        "provider": "openai",
        "model": "gpt-5.5",
        "web_search": False,
    },

    "WEB": {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "web_search": True,
    },

    "WEB_DEEP": {
        "provider": "openai",
        "model": "gpt-5.5",
        "web_search": True,
    },
}

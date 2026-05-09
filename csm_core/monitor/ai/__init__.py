"""AI enrichment helpers: comment sentiment + Zhihu answer summarization.

Both modules are optional — they're invoked only when the user has
opted in via ``MonitorConfig.ai_classify_comments`` /
``ai_summarize_zhihu``. They take an ``LLMClient`` so the caller can
decide which provider to spend tokens on.
"""

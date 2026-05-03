ARG BASE_IMAGE=nousresearch/hermes-agent:latest
FROM ${BASE_IMAGE}

USER root
WORKDIR /opt/hermes

# agent-browser does not automatically discover Playwright's versioned
# chrome path in the upstream Hermes image, so expose it via a stable symlink.
ENV AGENT_BROWSER_EXECUTABLE_PATH=/usr/local/bin/hermes-chrome

RUN PLAYWRIGHT_CHROME="$(find /opt/hermes/.playwright -type f -name chrome-headless-shell 2>/dev/null | head -n 1)" && \
    if [ -z "$PLAYWRIGHT_CHROME" ]; then PLAYWRIGHT_CHROME="$(find /opt/hermes/.playwright -type f -path '*/chrome-linux64/chrome' 2>/dev/null | head -n 1)"; fi && \
    test -n "$PLAYWRIGHT_CHROME" && \
    ln -sf "$PLAYWRIGHT_CHROME" "$AGENT_BROWSER_EXECUTABLE_PATH"

# Apply only the local runtime overrides on top of the official Hermes image.
COPY --chown=hermes:hermes .upstream-overlay/agent/smart_model_routing.py /opt/hermes/agent/smart_model_routing.py
COPY --chown=hermes:hermes .upstream-overlay/gateway/ /opt/hermes/gateway/
COPY --chown=hermes:hermes .upstream-overlay/hermes_cli/ /opt/hermes/hermes_cli/
COPY --chown=hermes:hermes .upstream-overlay/run_agent.py /opt/hermes/run_agent.py
COPY --chown=hermes:hermes .upstream-overlay/cli-config.yaml.example /opt/hermes/cli-config.yaml.example
COPY .upstream-overlay/patches/ensure_anthropic_normalizer.py /tmp/ensure_anthropic_normalizer.py
COPY .upstream-overlay/patches/ensure_gemini_local_proxy.py /tmp/ensure_gemini_local_proxy.py
RUN /opt/hermes/.venv/bin/python3 /tmp/ensure_anthropic_normalizer.py && rm -f /tmp/ensure_anthropic_normalizer.py
RUN /opt/hermes/.venv/bin/python3 /tmp/ensure_gemini_local_proxy.py && rm -f /tmp/ensure_gemini_local_proxy.py

RUN test -f /opt/hermes/gateway/run.py && \
    test -f /opt/hermes/run_agent.py && \
    test -f /opt/hermes/agent/smart_model_routing.py

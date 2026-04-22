ARG BASE_IMAGE=nousresearch/hermes-agent:latest
FROM ${BASE_IMAGE}

USER root
WORKDIR /opt/hermes

# Apply only the local runtime overrides on top of the official Hermes image.
COPY --chown=hermes:hermes .upstream-overlay/gateway/ /opt/hermes/gateway/
COPY --chown=hermes:hermes .upstream-overlay/hermes_cli/ /opt/hermes/hermes_cli/
COPY --chown=hermes:hermes .upstream-overlay/run_agent.py /opt/hermes/run_agent.py
COPY --chown=hermes:hermes .upstream-overlay/cli-config.yaml.example /opt/hermes/cli-config.yaml.example

RUN test -f /opt/hermes/gateway/run.py && \
    test -f /opt/hermes/run_agent.py

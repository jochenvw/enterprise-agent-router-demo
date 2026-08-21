import os

from opentelemetry import trace


def configure_telemetry(service_name: str) -> None:
    if not os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(
        connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"],
        resource_attributes={"service.name": service_name},
    )


def tracer() -> trace.Tracer:
    return trace.get_tracer("enterprise-agent-router")


"""SDK y RequestsTransport reales con adaptador local; ninguna llamada de red."""

import pytest


def test_202_body_timeout_no_se_reintenta(monkeypatch):
    email = pytest.importorskip("azure.communication.email")
    requests = pytest.importorskip("requests")
    from azure.core.pipeline.transport import RequestsTransport

    from homelab_dashboard.market_regime.settings import RegimeSettings
    from homelab_dashboard.notifications.acs import send

    accepted = []

    class AcceptedResponse(requests.Response):
        @property
        def content(self):
            raise requests.exceptions.ReadTimeout("Timeout leyendo body tras HTTP 202")

    class LocalAdapter(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            accepted.append(request)
            response = AcceptedResponse()
            response.status_code = 202
            response.request = request
            response.url = request.url
            response.headers["operation-id"] = "synthetic-operation"
            return response

        def close(self):
            pass

    session = requests.Session()
    session.trust_env = False
    session.mount("https://", LocalAdapter())
    session.mount("http://", LocalAdapter())
    transport = RequestsTransport(session=session)
    original = email.EmailClient.from_connection_string
    monkeypatch.setattr(
        email.EmailClient,
        "from_connection_string",
        lambda *args, **kwargs: original(*args, transport=transport, **kwargs),
    )
    settings = RegimeSettings(
        enabled=True,
        deliveries_enabled=True,
        acs_connection_string="endpoint=https://synthetic.communication.azure.com;accesskey=dGVzdA==",
        acs_email_sender="sender@example.com",
    )
    result = send(
        settings,
        channel="email",
        destination="recipient@example.com",
        subject="SINTETICO",
        text="Prueba sin red.",
    )
    assert len(accepted) == 1
    assert result.status == "INCIERTO"

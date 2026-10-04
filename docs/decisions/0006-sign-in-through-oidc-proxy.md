# ADR 0006: Sign-in through an OIDC reverse proxy

Status: proposed; amends the authentication line of ADR 0005. Basis: design v1.0 sections 2, 8 and 9.

ADR 0005 proposed running the OIDC authorization-code flow inside the API. The identity provider is still undecided, and Chinese enterprises commonly use providers (WeCom, DingTalk, Feishu, AD FS, Keycloak) with differing OIDC quirks. Running the flow in the API also puts token handling, refresh and logout into application code.

Decisions:

- An OIDC reverse proxy (for example oauth2-proxy) in front of the web app and API performs sign-in and sets the verified identity in a header (`SEQUENCE_VAULT_IDENTITY_HEADER`, default `X-Forwarded-Email`).
- The API trusts that header only when the request also carries the shared secret `X-Proxy-Secret` (`SEQUENCE_VAULT_PROXY_SECRET`), compared in constant time. Deploy the API so it is reachable only through the proxy.
- The subject maps to a provisioned `app_user`; unknown subjects get 403. Project membership and roles stay in the application database, managed by project administrators.
- State-changing requests must carry `X-Requested-With: sequence-vault`; browsers cannot add it cross-site without a CORS preflight, which the API does not allow. This complements `SameSite` session cookies at the proxy.
- Development only (`SEQUENCE_VAULT_ENV=development` and `SEQUENCE_VAULT_DEV_LOGIN=true`): an `X-Dev-User` header selects a provisioned user. Settings refuse this outside development.

Consequences: no OIDC library or token storage in the backend; the proxy configuration becomes part of deployment (P7). Changing identity providers needs no code change.

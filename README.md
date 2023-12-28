# OpenID Connect support for OpenStack clients

[![GitHub issues](https://img.shields.io/github/issues/vexxhost/keystoneauth-openid.svg)](https://github.com/vexxhost/keystoneauth-openid/issues)
[![GitHub license](https://img.shields.io/badge/license-Apache%202-blue.svg)](https://raw.githubusercontent.com/vexxhost/keystoneauth-openid/master/LICENSE)

This is an authentication plugin for OpenStack clients (namely for
the [keystoneauth1](https://github.com/openstack/keystoneauth) library) which
provides client support for authentication against an OpenStack Keystone server
configured to support OpenID Connect using Apache's
[mod_auth_openidc](https://github.com/zmartzone/mod_auth_openidc), as described
below.

## Available plugins

### `v3openid` plugin

This plugin will allow you to authenitcate with a keystone server that is configured to use `openid` as an auth option on `/etc/keystone/keystone.conf`

## Installation

Install it via pip:

    pip install keystoneauth-openid

Or clone the repo and install it:

    git clone https://github.com/vexxhost/keystoneauth-openid
    cd keystoneauth-openid
    pip install .

## Usage

### `v3openid` plugin

You have to specify the `v3openid` in the `--os-auth-type`. The
`<identity-provider>` and `<protocol>` must be provided by the OpenStack cloud
provider.

#### 1. Pass as command line option
- Unscoped token:

        openstack --os-auth-url https://keystone.example.org:5000/v3 \
            --os-auth-type v3openid \
            --os-identity-provider <identity-provider> \
            --os-protocol <protocol> \
            --os-identity-api-version 3 \
            token issue

- Scoped token:

        openstack --os-auth-url https://keystone.example.org:5000/v3 \
            --os-auth-type v3openid \
            --os-identity-provider <identity-provider> \
            --os-protocol <protocol> \
            --os-project-name <project> \
            --os-project-domain-name <project-domain> \
            --os-identity-api-version 3 \
            --os-openid-scope "openid profile email" \
            token issue

#### 2. Add to stackrc file

```bash
export OS_AUTH_TYPE=v3openid
export OS_AUTH_URL=https://keystone.example.org:5000/v3
export OS_IDENTITY_PROVIDER='<keystone-identity-provider>'
export OS_PROTOCOL=openid

```

### 3. Add to clouds.yml

- Unscoped token:

    ```yaml
    clouds:
        my_cloud:
            auth_type: v3openid
            auth_url: https://keystone.example.org:5000/v3
            identity_provider: <keystone-identity-provider>
            protocol: openid
    ```

- Scoped token:

    ```yaml
    clouds:
        my_cloud:
            auth_type: v3openid
            auth_url: https://keystone.example.org:5000/v3
            identity_provider: <keystone-identity-provider>
            protocol: openid
            auth:
                project_name: <project-name>
                project_domain_name: <domain-name>
    ```

invoke using
```
OS_CLOUD=my_cloud openstack token issue
```

## Keystone Server config

keystone configuration consists of the keystone.conf (as well as any domain-specific configs) and the Apache2 wsgi configuration.

### Configure /etc/keystone/keystone.conf

If domain specific configs are enabled on the server then this section needs to be added to each OpenID enabled domain

```ini
[openid]
claim_prefix = OIDC-
remote_id_attribute = OIDC-sub

```

Also, http://localhost:9990 needs to be added as a "Trusted Dashboard"

```ini
[federation]
trusted_dashboard=http://your-horizon-dashboard/auth/websso/
trusted_dashboard=http://localhost:9990/auth/websso/

```

### Configure wsgi-keystone.conf

There are 2 required "protected" Locations that need to be created.

* 1 Global redirect URL

    ```xml
    <Location /v3/auth/OS-FEDERATION/identity_providers/redirect>
        AuthType openid-connect
        Require valid-user
    </Location>
    ```

* 1 Location that is used for websso authentication. This is specific to the target OpenStack Keystone Identity Provider. See [callback_template](https://docs.openstack.org/keystone/latest/admin/federation/configure_federation.html#add-the-callback-template-websso) for more information

    ```xml
    <Location /v3/auth/OS-FEDERATION/identity_providers/<IDP-name>/protocols/openid/websso>
        Require valid-user
        AuthType openid-connect
        OIDCDiscoverURL http://localhost:15000/v3/auth/OS-FEDERATION/identity_providers/redirect?iss=<url-encoded-issuer>
    </Location>
    ```


For detailed configuration of mod_auth_oidc with Keycloak, see:
https://github.com/OpenIDC/mod_auth_openidc/wiki/Keycloak

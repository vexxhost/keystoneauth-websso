# Copyright 2016 Spanish National Research Council
# Copyright 2016 INDIGO-DataCloud
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from keystoneauth1.loading import opts
from keystoneauth1.loading._plugins.identity import v3

from keystoneauth_websso import plugin


class OpenIDConnect(v3.loading.BaseFederationLoader):

    @property
    def plugin_class(self):
        return plugin.OpenIDConnect

    def get_options(self):
        options = super(OpenIDConnect, self).get_options()

        options.extend(
            [
                opts.Opt(
                    "redirect-port",
                    default=9990,
                    type=int,
                    help="Port where the callback server will be "
                    "listening. By default this server will listen on "
                    "localhost and port 9990 (therefore the redirect URL "
                    "to be configured in the authentication server would "
                    "is http://localhost:9990), but you can adjust the "
                    "port here in case you cannot bind on that port.",
                ),
            ]
        )

        return options

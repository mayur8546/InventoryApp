"""Apps file for plugin app.

This initializes the plugin mechanisms and handles reloading throught the lifecycle.
The main code for plugin special sauce is in the plugin registry in `InvenTree/plugin/registry.py`.
"""

import logging

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

from maintenance_mode.core import set_maintenance_mode

from InvenTree.ready import canAppAccessDatabase
from plugin import registry
from plugin.helpers import check_git_version, log_error

logger = logging.getLogger('inventree')


class PluginAppConfig(AppConfig):
    """AppConfig for plugins."""

    name = 'plugin'

    def ready(self):
        """The ready method is extended to initialize plugins."""
        if not canAppAccessDatabase(allow_test=True, allow_plugins=True):
            logger.info("Skipping plugin loading sequence")  # pragma: no cover
        else:
            logger.info('Loading InvenTree plugins')

            if not registry.is_loading:
                # this is the first startup
                try:
                    from common.models import InvenTreeSetting
                    if InvenTreeSetting.get_setting('PLUGIN_ON_STARTUP', create=False, cache=False):
                        # make sure all plugins are installed
                        registry.install_plugin_file()
                except Exception:  # pragma: no cover
                    pass

                # get plugins and init them
                registry.plugin_modules = registry.collect_plugins()
                registry.load_plugins()

                # drop out of maintenance
                # makes sure we did not have an error in reloading and maintenance is still active
                set_maintenance_mode(False)

        # check git version
        registry.git_is_modern = check_git_version()

        if not registry.git_is_modern:  # pragma: no cover  # simulating old git seems not worth it for coverage
            log_error(_('Your environment has an outdated git version. This prevents InvenTree from loading plugin details.'), 'load')

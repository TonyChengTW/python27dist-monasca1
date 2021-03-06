# (C) Copyright 2015,2016 Hewlett Packard Enterprise Development LP
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import six

import logging
import time

from monasca_common.simport import simport
from monasca_notification.plugins import email_notifier
from monasca_notification.plugins import pagerduty_notifier
from monasca_notification.plugins import webhook_notifier

log = logging.getLogger(__name__)

possible_notifiers = None
configured_notifiers = None
statsd_counter = None

statsd = None
statsd_timer = None


def init(statsd_obj):
    global statsd, statsd_timer, \
        possible_notifiers, configured_notifiers,\
        statsd_counter

    statsd = statsd_obj
    statsd_timer = statsd.get_timer()

    statsd_counter = {}
    configured_notifiers = {}

    possible_notifiers = [
        email_notifier.EmailNotifier(log),
        webhook_notifier.WebhookNotifier(log),
        pagerduty_notifier.PagerdutyNotifier(log)
    ]


def load_plugins(config):
    global possible_notifiers

    for plugin_class in config.get("plugins", []):
        try:
            possible_notifiers.append(simport.load(plugin_class)(log))
        except Exception:
            log.exception("unable to load the class {0} , ignoring it".format(plugin_class))


def enabled_notifications():
    global configured_notifiers

    results = []
    for key in configured_notifiers:
        results.append(key.upper())
    return results


def config(cfg):
    global possible_notifiers, configured_notifiers, statsd_counter

    formatted_config = {t.lower(): v for t, v in six.iteritems(cfg)}
    for notifier in possible_notifiers:
        ntype = notifier.type.lower()
        if ntype in formatted_config:
            try:
                notifier.config(formatted_config[ntype])
                configured_notifiers[ntype] = notifier
                statsd_counter[ntype] = statsd.get_counter(notifier.statsd_name)
                log.info("{} notification ready".format(ntype))
            except Exception:
                log.exception("config exception for {}".format(ntype))
        else:
            log.warn("No config data for type: {}".format(ntype))
    config_with_no_notifiers = set(formatted_config.keys()) - set(configured_notifiers.keys())
    # Plugins section contains only additional plugins and should not be
    # considered as a separate plugin
    if 'plugins' in config_with_no_notifiers:
        config_with_no_notifiers.remove('plugins')
    if config_with_no_notifiers:
        log.warn("No notifiers found for {0}". format(", ".join(config_with_no_notifiers)))


def send_notifications(notifications):
    sent = []
    failed = []
    invalid = []

    for notification in notifications:
        ntype = notification.type
        if ntype not in configured_notifiers:
            log.warn("attempting to send unconfigured notification: {}".format(ntype))
            invalid.append(notification)
            continue

        notification.notification_timestamp = time.time()

        with statsd_timer.time(ntype + '_time'):
            result = send_single_notification(notification)

        if result:
            sent.append(notification)
            statsd_counter[ntype].increment(1)
        else:
            failed.append(notification)

    return sent, failed, invalid


def send_single_notification(notification):
    global configured_notifiers

    ntype = notification.type
    try:
        return configured_notifiers[ntype].send_notification(notification)
    except Exception:
        log.exception("send_notification exception for {}".format(ntype))
        return False

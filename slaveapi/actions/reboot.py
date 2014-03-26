from mozpoolclient import MozpoolHandler

from .results import SUCCESS, FAILURE
from ..clients.bugzilla import file_reboot_bug
from ..clients.ping import ping
from ..machines.base import wait_for_reboot
from ..slave import Slave, get_console

import logging
log = logging.getLogger(__name__)

def reboot(name):
    """Attempts to reboot the named slave a series of ways, escalating from
    peacefully to mercilessly. Details of what was attempted and the result
    are reported into the slave's problem tracking bug at the end. Reboots
    are attempted through the following means (from most peaceful to least
    merciful):

    * SSH: Logs into the machine via SSH and reboots it with an \
        appropriate command.

    * IPMI: Uses the slave's IPMI interface to initiate a hard \
        reboot. If the slave has no IPMI interface, this is skipped.

    * PDU: Powercycles the slave by turning off the power, and then \
        turning it back on.

    * Bugzilla: Requests that IT reboot the slave by updating or creating \
        the appropriate bugs.
    """
    status_text = ""
    slave = Slave(name)
    slave.load_inventory_info()
    slave.load_devices_info()
    slave.load_ipmi_info()
    slave.load_bug_info(createIfMissing=False)
    status_text += "Attempting SSH reboot..."

    alive = False
    # If the slave is pingable, try an SSH reboot...
    try:
        if ping(slave.fqdn):
            console = get_console(slave, usebuildbotslave=False)
            if console:
                # Sometimes the SSH session goes away before the command can
                # successfully complete. In order to avoid misinterpreting that
                # as some sort of other failure, we need to assume that it suceeds.
                # wait_for_reboot will confirm that the slave goes down before
                # coming back up, so this is OK to do.
                try:
                    console.reboot()
                except:
                    log.warning("%s - Eating exception during SSH reboot.", name, exc_info=True)
                    pass
                alive = wait_for_reboot(slave)
    except:
        log.exception("%s - Caught exception during SSH reboot.", name)

    # If there is a mozpool server associated
    if not alive and slave.mozpool_server:
        status_text += "Failed.\n"
        status_text += "Attempting reboot via Mozpool..."
        try:
            mozpoolhandler = MozpoolHandler(self.mozpool_server)
            mozpoolhandler.device_power_cycle(slave.name, None)
            alive = wait_for_reboot(slave)
        except:
            log.exception("%s - Caught exception during mozpool reboot.", name)

    # If that doesn't work, maybe an IPMI reboot will...
    if not alive and slave.ipmi:
        status_text += "Failed.\n"
        status_text += "Attempting IPMI reboot..."
        try:
            try:
                slave.ipmi.powercycle()
            except:
                log.warning("%s - Eating exception during IPMI reboot.", name, exc_info=True)
                pass
            alive = wait_for_reboot(slave)
        except:
            log.exception("%s - Caught exception during IPMI reboot.", name)

    # Mayhaps a PDU reboot?
    if not alive and slave.pdu:
        status_text += "Failed.\n"
        status_text += "Attempting PDU reboot..."
        try:
            try:
                slave.pdu.powercycle()
            except:
                log.warning("%s - Eating exception during PDU reboot.", name, exc_info=True)
                pass
            alive = wait_for_reboot(slave)
        except:
            log.exception("%s - Caught exception during PDU reboot.", name)

    if alive:
        # To minimize bugspam, no comment is added to the bug if we were
        # able to bring it back up.
        status_text += "Success!"
        return SUCCESS, status_text
    else:
        status_text += "Failed.\n"
        if slave.reboot_bug:
            status_text += "Slave already has reboot bug (%s), nothing to do." % slave.reboot_bug.id_
            return FAILURE, status_text
        else:
            if not slave.bug:
                slave.load_bug_info(createIfMissing=True)
            slave.reboot_bug = file_reboot_bug(slave)
            status_text += "Filed IT bug for reboot (bug %s)" % slave.reboot_bug.id_
            data = {}
            if not slave.bug.data["is_open"]:
                data["status"] = "REOPENED"
            slave.bug.add_comment(status_text, data=data)
            return FAILURE, status_text

from device import getDevice
from test import get_test, get_testinfo, TestException, SRC_DIR, TEST_DIR
import datetime
import json
import os
import urllib
import videocapture

CAPTURE_DIR = os.path.abspath(os.path.join(SRC_DIR, "../captures"))
GECKO_PROFILER_ADDON_DIR = os.path.join(SRC_DIR, "../src/GeckoProfilerAddon")
EIDETICKER_TEMP_DIR = "/tmp/eideticker"

def run_test(testkey, capture_device, appname, capture_name,
             device_prefs, extra_prefs={}, test_type=None, profile_file=None,
             request_log_file=None, actions_log_file=None,
             log_checkerboard_stats=False, extra_env_vars={},
             capture_area=None, no_capture=False, capture_file=None,
             sync_time=True, flush_caches=False):
    testinfo = get_testinfo(testkey)
    print "Testinfo: %s" % testinfo

    if device_prefs['devicetype'] == 'android' and not appname and \
            not testinfo.get('appname'):
        raise TestException("Must specify an appname (with --app-name) on Android "
                            "when not spec'd by test")

    if not os.path.exists(EIDETICKER_TEMP_DIR):
        os.mkdir(EIDETICKER_TEMP_DIR)
    if not os.path.isdir(EIDETICKER_TEMP_DIR):
        raise TestException("Could not open eideticker temporary directory")

    appname = testinfo.get('appname') or appname

    capture_name = capture_name
    if not capture_name:
        capture_name = testinfo['shortDesc']
    if not capture_file and not no_capture:
        capture_file = os.path.join(CAPTURE_DIR, "capture-%s.zip" %
                                    datetime.datetime.now().isoformat())
    elif no_capture:
        capture_file = None

    # Create a device object to interface with the phone
    device = getDevice(**device_prefs)

    # synchronize time unless instructed not to
    if sync_time:
        device.synchronizeTime()

    capture_metadata = {
        'name': capture_name,
        'testpath': testinfo['relpath'],
        'app': appname,
        'device': device.model,
        'devicetype': device_prefs['devicetype'],
        'startupTest': testinfo['type'] == 'startup'
        }

    # note: url params for startup tests currently not supported
    if testinfo.get('urlOverride'):
        testpath_rel = testinfo['urlOverride']
    else:
        testpath_rel = testinfo['relpath']
    if testinfo.get('urlParams'):
        testpath_rel += "?%s" % urllib.quote_plus(testinfo.get('urlParams'))

    capture_controller = videocapture.CaptureController(capture_device, capture_area,
                                                        custom_tempdir=EIDETICKER_TEMP_DIR)

    testtype = test_type or testinfo['type']

    # get actions for web tests
    actions = None
    if testtype == 'web':
        actions_path = os.path.join(testinfo['here'], "actions.json")
        try:
            with open(actions_path) as f:
                actions = json.loads(f.read())
        except EnvironmentError:
            raise TestException("Couldn't open actions file '%s'" % actions_path)

    test = get_test(testinfo, devicetype = device_prefs['devicetype'],
                    testtype = testtype,
                    testpath_rel = testpath_rel, device = device,
                    actions = actions, extra_prefs = extra_prefs,
                    extra_env_vars = extra_env_vars,
                    flush_caches = flush_caches,
                    capture_file = capture_file,
                    capture_controller = capture_controller,
                    capture_metadata = capture_metadata,
                    appname = appname,
                    request_log_file = request_log_file,
                    actions_log_file = actions_log_file,
                    log_checkerboard_stats = log_checkerboard_stats,
                    profile_file = profile_file,
                    gecko_profiler_addon_dir=GECKO_PROFILER_ADDON_DIR,
                    docroot = TEST_DIR,
                    tempdir = EIDETICKER_TEMP_DIR)

    test.run()
    test.cleanup()

    if capture_file:
        try:
            capture_controller.convert_capture(test.start_frame, test.end_frame)
        except KeyboardInterrupt:
            raise TestException("Aborting because of keyboard interrupt")

    return test.testlog

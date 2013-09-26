# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import mozdevice
import mozprofile
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
import log

class AndroidBrowserRunner(log.LoggingMixin):

    remote_profile_dir = None
    intent = "android.intent.action.VIEW"

    def __init__(self, dm, appname, url, tmpdir, preinitialize_user_profile=False,
                 open_url_after_launch=False, enable_profiling=False,
                 gecko_profiler_addon_dir=None, extra_prefs={},
                 extra_env_vars={}, flush_caches=False):
        self.dm = dm
        self.appname = appname
        self.url = url
        self.tmpdir = tmpdir
        self.preinitialize_user_profile = preinitialize_user_profile
        self.open_url_after_launch = open_url_after_launch
        self.enable_profiling = enable_profiling
        self.gecko_profiler_addon_dir = gecko_profiler_addon_dir
        self.extra_prefs = extra_prefs
        self.remote_profile_dir = None
        self.extra_env_vars = extra_env_vars
        self.flush_caches = flush_caches

        activity_mappings = {
            'com.android.browser': '.BrowserActivity',
            'com.google.android.browser': 'com.android.browser.BrowserActivity',
            'com.android.chrome': '.Main',
            'com.opera.browser': 'com.opera.Opera',
            'mobi.mgeek.TunnyBrowser': '.BrowserActivity' # Dolphin
            }

        # use activity mapping if not mozilla
        if self.appname.startswith('org.mozilla'):
            self.activity = '.App'
        else:
            self.activity = activity_mappings[self.appname]

    # return a temporary directory containing profile, apk, and shared libs
    def get_profile_and_symbols(self):
        if not self.enable_profiling:
           raise Exception("Can't get profile if it isn't started with the profiling option")

        files_to_package = []

        # create a temporary directory to place the profile and shared libraries
        profiledir = tempfile.mkdtemp(dir=self.tmpdir)

        # remove previous profiles if there is one
        sps_profile_path = os.path.join(profiledir, "fennec_profile.txt")
        if os.path.exists(sps_profile_path):
            os.remove(sps_profile_path)

        self.log("Fetching fennec_profile.txt")
        self.dm.getFile(self.remote_sps_profile_location, sps_profile_path)
        files_to_package.append(sps_profile_path)

        # FIXME: We still get a useful profile without the symbols from the apk
        # make doing this optional so we don't require a rooted device
        self.log("Fetching app symbols")
        local_apk_path = os.path.join(profiledir, "symbol.apk")
        self.dm.getAPK(self.appname, local_apk_path)
        files_to_package.append(local_apk_path)

        # get all the symbols library for symbolication
        self.log("Fetching system libraries")
        libpaths = [ "/system/lib",
                     "/system/lib/egl",
                     "/system/lib/hw",
                     "/system/vendor/lib",
                     "/system/vendor/lib/egl",
                     "/system/vendor/lib/hw",
                     "/system/b2g" ]

        for libpath in libpaths:
             self.log("Fetching from: %s" % libpath)
             dirlist = self.dm.listFiles(libpath)
             for filename in dirlist:
                 filename = filename.strip()
                 if filename.endswith(".so"):
                     lib_path = os.path.join(profiledir, filename)
                     remotefilename = libpath + '/' + filename
                     self.dm.getFile(remotefilename, lib_path)
                     files_to_package.append(lib_path);

        return profiledir

    def initialize_user_profile(self):
        # This is broken out from start() so we can call it explicitly if
        # we want to initialize the user profile by starting the app seperate
        # from the test itself
        if self.appname == "com.android.chrome":
            # for chrome, we just delete existing browser state (opened tabs, etc.)
            # so we can start reasonably fresh
            self.dm.shellCheckOutput(["sh", "-c",
                                      "rm -f /data/user/0/com.android.chrome/files/*"],
                                     root=True)
        elif self.appname == "com.google.android.browser":
            # for stock browser, ditto
            self.dm.shellCheckOutput(["rm", "-f",
                                      "/data/user/0/com.google.android.browser/cache/browser_state.parcel"],
                                     root=True)
        elif not self.appname.startswith('org.mozilla'):
            # some other browser which we don't know how to handle, just
            # return
            return

        preferences = { 'gfx.show_checkerboard_pattern': False,
                        'browser.firstrun.show.uidiscovery': False,
                        'layers.low-precision-buffer': False, # bug 815175
                        'toolkit.telemetry.prompted': 2,
                        'toolkit.telemetry.rejected': True }
        # Add frame counter to correlate video capture with profile
        if self.enable_profiling:
            preferences['layers.acceleration.frame-counter'] = True

        preferences.update(self.extra_prefs)
        profile = mozprofile.Profile(preferences = preferences)
        self.remote_profile_dir = "/".join([self.dm.getDeviceRoot(),
                                            os.path.basename(profile.profile)])
        self.dm.pushDir(profile.profile, self.remote_profile_dir)
        if self.preinitialize_user_profile:
            # initialize user profile by launching to about:home then
            # waiting for 10 seconds
            self.launch_fennec(None, "about:home")
            time.sleep(10)
            self.dm.killProcess(self.appname)

    def maybe_flush_caches(self):
        if self.flush_caches:
            self.log("Flushing caches")
            output = self.dm.shellCheckOutput(["sh", "-c",
                                               "echo 3 > /proc/sys/vm/drop_caches"],
                                              root=True)
            self.log(output)

    def start(self):
        self.log("Starting %s... " % self.appname)

        url = self.url
        if self.open_url_after_launch:
            url = None

        # for fennec only, we create and use a profile
        if self.appname.startswith('org.mozilla'):
            if not self.remote_profile_dir:
                self.initialize_user_profile()

            if self.enable_profiling:
                mozEnv = { "MOZ_PROFILER_STARTUP": "true" }
            else:
                mozEnv = {}
            mozEnv.update(self.extra_env_vars)

            # launch fennec for reals
            self.launch_fennec(mozEnv, url)
        else:
            self.is_profiling = False # never profiling with non-fennec browsers
            self.maybe_flush_caches()
            self.dm.launchApplication(self.appname, self.activity, self.intent,
                                      url=url)

    def open_url(self):
        self.maybe_flush_caches()
        self.dm.launchApplication(self.appname, self.activity, self.intent,
                                  url=self.url, failIfRunning=False)

    def launch_fennec(self, mozEnv, url):
        # sometimes fennec fails to start, so we'll try three times...
        for i in range(3):
            self.maybe_flush_caches()
            self.log("Launching %s (try %s of 3)" % (self.appname, i+1))
            try:
                self.dm.launchFennec(self.appname, url=url, mozEnv=mozEnv,
                                     extraArgs=["-profile",
                                                self.remote_profile_dir])
            except mozdevice.DMError:
                continue
            return # Ok!
        raise Exception("Failed to start Fennec after three tries")

    def save_profile(self):
        # Dump the profile (don't process it yet because we need to cleanup
        # the capture first)
        self.log("Saving sps performance profile")
        appPID = self.dm.getPIDs(self.appname)[0]
        self.dm.sendSaveProfileSignal(self.appname)
        self.remote_sps_profile_location = "/mnt/sdcard/profile_0_%s.txt" % appPID
        # Saving goes through the main event loop so give it time to flush
        time.sleep(10)
        self.log("SPS profile should be saved")

    def process_profile(self, profile_file):
        xrebindir = os.path.join(os.environ['XRE'], 'bin') if 'XRE' in os.environ else ''
        szippath = os.environ['SZIP'] if 'SZIP' in os.environ else 'szip'
        addondir = self.gecko_profiler_addon_dir

        tempdir = self.get_profile_and_symbols()
        symbolapk = os.path.join(tempdir, 'symbol.apk')
        if os.path.exists(symbolapk):
            # extract and un-szip shared libs
            zipfile.ZipFile(symbolapk).extractall(tempdir)
            # find <dir> -wholename '<dir>/*/*.so' -exec szip -d {} \; -exec mv {} <dir> \;
            subprocess.check_call(['find', tempdir,
                '-wholename', os.path.join(tempdir, '*', '*.so'),
                '-exec', szippath, '-d', '{}', ';',
                '-exec', 'mv', '{}', tempdir, ';'])

        # run the symbolicating code
        symbolicator = subprocess.Popen([
            os.path.join(xrebindir, 'run-mozilla.sh'), os.path.join(xrebindir, 'xpcshell'),
            '-f', os.path.join('data', 'ProgressReporter.js'),
            '-f', os.path.join('data', 'SymbolicateXPCShell.js'),
            '-f', os.path.join('data', 'CmdRunWorker.js'),
            '-f', os.path.join('data', 'SymbolicateWorker.js'),
            os.path.join('data', 'SymbolicateMain.js'),
            os.path.join(tempdir, 'fennec_profile.txt'), tempdir, self.appname],
            cwd=addondir,
            stdout=subprocess.PIPE)

        symbolicated_profile = None
        line = symbolicator.stdout.readline()
        while line:
            line = line.strip()
            if line.startswith('{') and line.endswith('}'):
                # assume JSON format
                symbolicated_profile = line
            else:
                self.log('Symbolicate: ' + line)
            line = symbolicator.stdout.readline()

        if symbolicator.wait() == 0:
            if symbolicated_profile:
                with zipfile.ZipFile(profile_file, 'w') as out:
                    out.writestr('symbolicated_profile.txt', symbolicated_profile)
            else:
                raise Exception('Failed to get symbolication output')
        else:
            raise Exception('Failed to symbolicate (returned %d)' % symbolicator.returncode)

        # safe to get rid of temp dir
        shutil.rmtree(tempdir)

    def cleanup(self):
        # stops the process and cleans up after a run
        self.dm.killProcess(self.appname)

        # Remove the Mozilla profile from the sdcard (not to be confused with
        # the sampling profile)
        if self.remote_profile_dir:
            self.dm.removeDir(self.remote_profile_dir)
            self.log("WARNING: Failed to remove profile (%s) from device" %
                     self.remote_profile_dir)

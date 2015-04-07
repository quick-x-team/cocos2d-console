#!/usr/bin/python
# ----------------------------------------------------------------------------
# cocos2d "upgrade" plugin
#
# Copyright 2014 (C) Chukong-inc.com
#
# Author : Zhangbin(zhangbin@cocos2d-x.org)
#
# License: MIT
# ----------------------------------------------------------------------------
'''
"compile" plugin for cocos command line tool
'''

__docformat__ = 'restructuredtext'

import cocos
import cocos_project
import os
import os.path
import re
import sys
import shutil
import subprocess

def run_shell(cmd, cwd=None):
    p = subprocess.Popen(cmd, shell=True, cwd=cwd)
    p.wait()

    return p.returncode

class CCPluginUpgrade(cocos.CCPlugin):
    """
    upgrade a project
    """

    PROJ_CFG_KEY_ENGINE_VERSION = "engine_version"
    PROJ_CFG_KEY_ENGINE_TYPE = "engine_type"

    FRAMEWORKS_VAR_KEY = "COCOS_FRAMEWORKS"

    @staticmethod
    def plugin_name():
      return "upgrade"

    @staticmethod
    def brief_description():
        return "Upgrade the engine version of project."

    def parse_args(self, argv):
        from argparse import ArgumentParser

        parser = ArgumentParser(prog="cocos %s" % self.__class__.plugin_name(),
                                description=self.__class__.brief_description())

        parser.add_argument("-s", "--src",
                            dest="src_dir",
                            help="Project base directory.")

        parser.add_argument("-e", "--engine-version",
                            dest="engine_version",
                            help="The target engine version to upgrade.")

        parser.add_argument("--no-backup",
                            dest="no_backup", action="store_true",
                            help="Specify not backup the project before upgrade.")

        parser.add_argument("--backup-dir",
                            dest="backup_dir",
                            help="Specify the backup directory. Default is same level with project directory.")

        parser.add_argument("-l", "--language",
                            choices=["cpp", "lua", "js"],
                            help="Major programming language you want to use in project to upgrade, should be [cpp | lua | js]")

        (args, unknown) = parser.parse_known_args(argv)

        if len(unknown) > 0:
            cocos.Logging.warning("Unknow args : %s" % unknown)

        self.init_args(args)

    def init_args(self, args):
        # check the project directory
        if args.src_dir is None:
            raise cocos.CCPluginError("Please specify the project path by '-s, --src'.")

        if os.path.isabs(args.src_dir):
            self.proj_dir = args.src_dir
        else:
            self.proj_dir = os.path.abspath(os.path.join(os.getcwd(), args.src_dir))

        # strip the "/" or "\" at the end of project directory
        self.proj_dir = self.proj_dir.rstrip(os.path.sep)

        if not os.path.isdir(self.proj_dir):
            raise cocos.CCPluginError("%s is not a directory." % self.proj_dir)

        try:
            self.proj_obj = cocos_project.Project(self.proj_dir)
        except cocos.CCPluginError as e:
            print e
            self.proj_obj = None
            self.check_ccs_project()
            if self.proj_name is None:
                raise cocos.CCPluginError("There is no valid project to upgrade in directory '%s'." % self.proj_dir)

        if self.proj_obj is None:
            # check the language specified by -l
            if args.language is None:
                raise cocos.CCPluginError("Please specify the language of project to upgrade by '-l, --language'.")
            self.proj_lang = args.language   

        else:
            # check the engine version specified by -e
            if args.engine_version is None:
                raise cocos.CCPluginError("Please specify the engine version to upgrade by '-e, --engine-version'.")    

            self.target_version = args.engine_version
            framework_path = self.get_frameworks_path()
            if not os.path.isdir(os.path.join(framework_path, self.target_version)):
                raise cocos.CCPluginError("Engine version %s is not existed in %s" % (self.target_version, framework_path))    

            # check the engine type of project
            engine_type = self.proj_obj.get_proj_config(CCPluginUpgrade.PROJ_CFG_KEY_ENGINE_TYPE)
            if engine_type is None or engine_type != "prebuilt":
                raise cocos.CCPluginError("Now only support upgrade projects using prebuilt engine.")    

            # check the current engine version of project
            self.current_version = self.proj_obj.get_proj_config(CCPluginUpgrade.PROJ_CFG_KEY_ENGINE_VERSION)
            if self.current_version is None:
                raise cocos.CCPluginError("Parse the current engine version of %s failed." % self.proj_dir)    

            # if current version is same with target version. tip message
            if self.current_version == self.target_version:
                cocos.Logging.warning(
                    "Current version '%s' is same with target version '%s'. It's NOT necessary to upgrade project."
                    % (self.current_version, self.target_version))
                exit()

        self.no_backup = args.no_backup
        proj_par_dir, proj_name = os.path.split(self.proj_dir)
        self.proj_dir_name = proj_name
        if self.proj_obj is None:
            self.backup_name = "%s-%s" % (proj_name, "ccs")
        else:
            self.backup_name = "%s-%s" % (proj_name, self.current_version)
        if not self.no_backup:
            if args.backup_dir is None:
                self.backup_dir = proj_par_dir
            else:
                if os.path.isabs(args.backup_dir):
                    self.backup_dir = args.backup_dir
                else:
                    self.backup_dir = os.path.abspath(os.path.join(os.getcwd(), args.backup_dir))
        else:
            import tempfile
            self.backup_dir = tempfile.gettempdir()

        if not self.proj_obj is None:
            self.init_projdir_info()

    def init_projdir_info(self):
        projects_dir = self.proj_dir
        if self.proj_obj._is_script_project():
            projects_dir = os.path.join(self.proj_dir, "frameworks/runtime-src")

        # get projects dir of all platforms
        self.xcode_proj_dir = os.path.join(projects_dir, "proj.ios_mac")
        self.android_proj_dir = os.path.join(projects_dir, "proj.android")
        self.win32_proj_dir = os.path.join(projects_dir, "proj.win32")

    def check_ccs_project(self):
        print "Checking CocosStudio project......"
        proj_dir = self.proj_dir
        for filename in os.listdir(proj_dir):
            if filename[-4:] != ".ccs":
                continue
            fullpath = os.path.join(proj_dir, filename)
            if not os.path.isfile(fullpath):
                continue
            f = open(fullpath, "rb")
            content = f.read()
            find_tag = '(PropertyGroup Name=\")(\S*)(\")'
            match = re.search(find_tag, content)
            if match is None:
                continue
            self.proj_name = match.group(2)
            print "Found CocosStudio project: %s" % self.proj_name
            break

    def upgrade_project(self):
        # backup the project
        self.backup_project()

        upgrade_succeed = False
        rollback_succeed = False
        try:
            # do the upgrading
            self.do_upgrade()
            upgrade_succeed = True
        except Exception as upgradeError:
            # exception occurred, roll back
            cocos.Logging.warning("Upgrade project failed: %s" % upgradeError)
            try:
                self.roll_back()
                rollback_succeed = True
            except Exception as rollbackError:
                cocos.Logging.warning("Rolling back failed: %s" % rollbackError)
                cocos.Logging.warning("Please manually roll back the project from %s" % self.backup_proj_path)

        if upgrade_succeed:
            # upgrade succeed
            if self.no_backup:
                # --no-backup specified, remove the backup folder
                shutil.rmtree(self.backup_proj_path, True)
        else:
            # upgrade failed
            if rollback_succeed:
                # rollback succeed, remove the backup folder
                shutil.rmtree(self.backup_proj_path, True)

    def backup_project(self):
        self.backup_proj_path = os.path.join(self.backup_dir, self.backup_name)
        if os.path.exists(self.backup_proj_path):
            self.backup_name = "%s-%s" % (self.backup_name, self.get_current_time())
            self.backup_proj_path = os.path.join(self.backup_dir, self.backup_name)

        if not self.no_backup:
            cocos.Logging.info("Backup the project %s to %s" % (self.proj_dir, self.backup_proj_path))

        cpy_cfg = {
            "from": self.proj_dir,
            "to": self.backup_proj_path,
            "exclude": [
                "proj.ios_mac/build",
                "proj.android/bin",
                "proj.android/assets",
                "proj.android/gen",
                "proj.android/obj",
                "proj.win32/[Dd]ebug.win32",
                "proj.win32/[Rr]elease.win32"
            ]
        }
        cocos.copy_files_with_config(cpy_cfg, self.proj_dir, self.backup_proj_path)

    def roll_back(self):
        cocos.Logging.warning("Rolling back...")
        # remove the project (it's broken)
        if os.path.exists(self.proj_dir):
            shutil.rmtree(self.proj_dir)

        # copy the backup folder to project folder
        cpy_cfg = {
            "from": self.backup_proj_path,
            "to": self.proj_dir
        }
        cocos.copy_files_with_config(cpy_cfg, self.backup_proj_path, self.proj_dir)
        cocos.Logging.warning("Rolling back finished!")

    def do_upgrade(self):
        if self.proj_obj is None:
            self.upgrade_full_project()
            return

        # upgrade the project configuration
        modify_files = self.gather_config_files()
        for file_path in modify_files:
            f = open(file_path)
            file_content = f.read()
            f.close()

            file_content = file_content.replace(self.current_version, self.target_version)

            f = open(file_path, "w")
            f.write(file_content)
            f.close()

        # upgrade the java files
        self.upgrade_java()

        # upgrade script project related
        if self.proj_obj._is_script_project():
            self.upgrade_scripts()

        # upgrade .cocos-project.json
        self.upgrade_project_json()

    def upgrade_full_project(self):
        proj_dir = self.proj_dir
        proj_par_dir, proj_dir_name = os.path.split(proj_dir)
        proj_name = self.proj_name
        proj_lang = self.proj_lang
        package_name = "com.cocos.%s.%s" % (proj_lang, proj_name)

        shutil.rmtree(proj_dir)
        cmd = "cocos new %s -l %s -p %s -d %s" % (proj_name, proj_lang, package_name, proj_par_dir)
        if proj_lang != 'cpp':
            cmd += ' -t runtime'
        ecode = run_shell(cmd)
        if ecode:
            raise cocos.CCPluginError("Failed to create new project!")

        if not os.path.exists(proj_dir):
            new_proj_dir = os.path.join(proj_par_dir, proj_name)
            if not os.path.exists(new_proj_dir):
                raise cocos.CCPluginError("Failed to create new project!")
            cpy_cfg = {
                "from": new_proj_dir,
                "to": proj_dir
            }
            cocos.copy_files_with_config(cpy_cfg, new_proj_dir, proj_dir)
            shutil.rmtree(new_proj_dir)

        # copy the backup folder to project folder
        cpy_cfg = {
            "from": self.backup_proj_path,
            "to": proj_dir
        }
        cocos.copy_files_with_config(cpy_cfg, self.backup_proj_path, proj_dir)
        cocos.Logging.warning("Upgrad project finished!")

    def upgrade_java(self):
        cocos.Logging.info("Upgrading the java files...")
        proj_java_dirs = [
            "src", "org", "cocos2dx", "lib"
        ]
        engine_java_dirs = [
            "cocos", "platform", "android", "java", "src", "org", "cocos2dx", "lib"
        ]
        proj_java_path = self.android_proj_dir
        for dir in proj_java_dirs:
            proj_java_path = os.path.join(proj_java_path, dir)

        engine_java_path = os.path.join(self.get_frameworks_path(), self.target_version)
        for dir in engine_java_dirs:
            engine_java_path = os.path.join(engine_java_path, dir)

        if not os.path.exists(proj_java_path):
            cocos.Logging.warning("Java file path %s is not existed." % proj_java_path)
            return

        if not os.path.exists(engine_java_path):
            cocos.Logging.warning("Java file path %s is not existed." % engine_java_path)
            return

        try:
            shutil.rmtree(proj_java_path)
            cpy_cfg = {
                "from": engine_java_path,
                "to": proj_java_path,
                "include": [
                    "*.java"
                ]
            }
            cocos.copy_files_with_config(cpy_cfg, engine_java_path, proj_java_path)
        except Exception as e:
            cocos.Logging.warning("Replace the java files failed : %s" % e)
            cocos.Logging.warning("Please replace the java files from %s to %s manually." % (engine_java_path, proj_java_path))

    def upgrade_scripts(self):
        cocos.Logging.info("Upgrading the script files...")
        if self.proj_obj._is_lua_project():
            proj_script_path = os.path.join(self.proj_dir, "src/cocos")
            engine_script_path = os.path.join(self.get_frameworks_path(), self.target_version, "cocos/scripting/lua-bindings/script")
            rule = "*.lua"
        else:
            proj_script_path = os.path.join(self.proj_dir, "script")
            engine_script_path = os.path.join(self.get_frameworks_path(), self.target_version, "cocos/scripting/js-bindings/script")
            rule = "*.js"

        if not os.path.exists(proj_script_path):
            cocos.Logging.warning("Script file path %s is not existed." % proj_script_path)
            return

        if not os.path.exists(engine_script_path):
            cocos.Logging.warning("Script file path %s is not existed." % engine_script_path)
            return

        try:
            shutil.rmtree(proj_script_path)
            cpy_cfg = {
                "from": engine_script_path,
                "to": proj_script_path,
                "include": [
                    rule
                ]
            }
            cocos.copy_files_with_config(cpy_cfg, engine_script_path, proj_script_path)
        except Exception as e:
            cocos.Logging.warning("Replace the java files failed : %s" % e)
            cocos.Logging.warning("Please replace the java files from %s to %s manually." % (engine_script_path, proj_script_path))

    def upgrade_project_json(self):
        cocos.Logging.info("Upgrading the .cocos-project.json...")
        self.proj_obj.write_proj_config(CCPluginUpgrade.PROJ_CFG_KEY_ENGINE_VERSION, self.target_version)

    def gather_config_files(self):
        # gather config files
        ret = []
        if os.path.exists(self.xcode_proj_dir):
            for name in os.listdir(self.xcode_proj_dir):
                if re.match(r".*\.xcodeproj$", name):
                    ret.append(os.path.join(self.xcode_proj_dir, name, "project.pbxproj"))

        if os.path.exists(self.android_proj_dir):
            ret.append(os.path.join(self.android_proj_dir, "build-cfg.json"))

        if os.path.exists(self.win32_proj_dir):
            for name in os.listdir(self.win32_proj_dir):
                if re.match(r".*\.vcxproj$", name):
                    ret.append(os.path.join(self.win32_proj_dir, name))

        return ret

    def get_current_time(self):
        import time
        return time.strftime("%Y%m%d%H%M%S", time.localtime(time.time()))

    def get_frameworks_path(self):
        return cocos.check_environment_variable(CCPluginUpgrade.FRAMEWORKS_VAR_KEY)

    def run(self, argv, dependencies):
        self.parse_args(argv)

        self.upgrade_project()

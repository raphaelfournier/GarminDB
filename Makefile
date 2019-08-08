#
# This Makefile handles downloading data from Garmin Connect and generating SQLite DB files from that data. The Makefile targets handle the dependaancies
# between downloading and geenrating varies types of data. It wraps the core Python scripts and runs them with appropriate parameters.
#
PROJECT_BASE=$(PWD)

include defines.mk

#
# Install Python dependancies as root?
#
ifeq ($(INSTALL_DEPS_TO_SYSTEM), y)
	DEPS_SUDO = sudo
else
	DEPS_SUDO =
endif


#
# All third party Python packages needed to use the project. They will be installed with pip.
#
PYTHON_PACKAGES=sqlalchemy requests python-dateutil enum34 progressbar2 PyInstaller matplotlib


#
# Master targets
#
all: update_dbs

# install all needed code
setup: update deps

clean_dbs: clean_mshealth_db clean_fitbit_db clean_garmin_dbs

# build dbs from already downloaded data files
build_dbs: build_garmin mshealth fitbit
create_dbs: garmin mshealth fitbit
create_copy_dbs: copy_garmin mshealth fitbit

# delete the exisitng dbs and build new dbs from already downloaded data files
rebuild_dbs: clean_dbs build_dbs

# update the exisitng dbs by downloading data files for dates after the last in the dbs and update the dbs
update_dbs: update_garmin
update_copy_dbs: copy_garmin_latest

release: zip_packages


#
# Project maintainance targets
#
update: submodules_update
	git pull --rebase

submodules_update:
	git submodule init
	git submodule update

deps_tcxparser:
	cd python-tcxparser && python2 setup.py install --record files.txt

clean_deps_tcxparser:
	cd python-tcxparser && cat files.txt | xargs rm -rf

install_deps: deps_tcxparser
	for package in $(PYTHON_PACKAGES); do \
		pip install --upgrade  $$package; \
	done

deps:
	$(DEPS_SUDO) $(MAKE) install_deps

remove_deps: clean_deps_tcxparser
	for package in $(PYTHON_PACKAGES); do \
		pip uninstall -y $$package; \
	done

clean_deps:
	$(DEPS_SUDO) $(MAKE) remove_deps

clean: test_clean
	rm -f *.pyc
	rm -f Fit/*.pyc
	rm -f HealthDB/*.pyc
	rm -f GarminDB/*.pyc
	rm -f FitBitDB/*.pyc
	rm -f $(BUGREPORT)
	rm -f *.log
	rm -rf dist
	rm -rf build
	rm -f *.spec
	rm -f *.zip
	rm -f *.png
	rm -f *.txt


#
# Fitness System independant targets
#
$(BACKUP_DIR):
	mkdir -p $(BACKUP_DIR)

EPOCH=$(shell date +'%s')
backup: $(BACKUP_DIR)
	zip -r $(BACKUP_DIR)/$(EPOCH)_dbs.zip $(DB_DIR)

PLATFORM=$(shell uname)
VERSION=$(shell python2 garmin.py --version)
BIN_FILES=dist/garmin dist/graphs dist/fitbit dist/mshealth
ZIP_FILES=dist_files/download_create_dbs.sh dist_files/download_update_dbs.sh dist_files/copy_create_dbs.sh dist_files/copy_update_dbs.sh
zip_packages: package_garmin package_fitbit package_mshealth
	zip -j -r GarminDb_$(PLATFORM)_$(VERSION).zip GarminConnectConfig.json.example $(BIN_FILES) $(ZIP_FILES)

graphs:
	python2 graphs.py --all

checkup:
	python2 checkup.py --goals

#
# Garmin targets
#
garmin:
	python2 garmin.py --all --download --import --analyze

build_garmin:
	python2 garmin.py --all --import --analyze

copy_garmin:
	python2 garmin.py --all --copy --import --analyze

update_garmin:
	python2 garmin.py --all --download --import --analyze --latest

copy_garmin_latest:
	python2 garmin.py --all --copy --import --analyze --latest

clean_garmin_dbs:
	python2 garmin.py --delete_db

package_garmin:
	pyinstaller --clean --noconfirm --onefile garmin.py
	pyinstaller --clean --noconfirm --onefile graphs.py
	pyinstaller --clean --noconfirm --onefile checkup.py



#
# FitBit target
#
fitbit:
	python2 fitbit.py

clean_fitbit_db:
	python2 fitbit.py --delete_db

package_fitbit:
	pyinstaller --clean --noconfirm --onefile fitbit.py


#
# MS Health target
#
mshealth: $(MSHEALTH_DB)
	python2 mshealth.py

clean_mshealth_db:
	python2 mshealth.py --delete_db

package_mshealth:
	pyinstaller --clean --noconfirm --onefile mshealth.py


#
# test targets
#
test:
	export PROJECT_BASE=$(PROJECT_BASE) && $(MAKE) -C test

test_clean:
	export PROJECT_BASE=$(PROJECT_BASE) && $(MAKE) -C test clean


#
# bugreport target
#
bugreport:
	uname -a > $(BUGREPORT)
	which python2 >> $(BUGREPORT)
	python2 --version >> $(BUGREPORT) 2>&1
	echo $(PYTHON_PACKAGES)
	for package in $(PYTHON_PACKAGES); do \
		pip show $$package >> $(BUGREPORT); \
	done

.PHONY: all setup create_dbs rebuild_dbs update_dbs clean clean_dbs test zip_packages release

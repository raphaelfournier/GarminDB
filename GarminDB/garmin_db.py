"""Objects representing a database and database objects for storing health data from a Garmin device."""

__author__ = "Tom Goetz"
__copyright__ = "Copyright Tom Goetz"
__license__ = "GPL"

import os
import datetime
import logging
from sqlalchemy import Column, Integer, Date, DateTime, Time, Float, String, Enum, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property

import HealthDB
import Fit
import Fit.conversions as conversions
from extra_data import ExtraData


logger = logging.getLogger(__name__)


class GarminDB(HealthDB.DB):
    """Object representing a database for storing health data from a Garmin device."""

    Base = declarative_base()
    db_name = 'garmin'
    db_version = 13

    class _DbVersion(Base, HealthDB.DbVersionObject):
        pass

    def __init__(self, db_params_dict, debug=False):
        """
        Return an instance of GarminDB.

        Paramters:
            db_params_dict (dict): Config data for accessing the database
            debug (Boolean): enable debug logging
        """
        super(GarminDB, self).__init__(db_params_dict, debug)
        GarminDB.Base.metadata.create_all(self.engine)
        self.version = GarminDB._DbVersion()
        self.version.version_check(self, self.db_version)
        self.tables = [Attributes, Device, DeviceInfo, File, Weight, Stress, Sleep, SleepEvents, RestingHeartRate, DailySummary, DailyExtraData]
        for table in self.tables:
            self.version.table_version_check(self, table)
            if not self.version.view_version_check(self, table):
                table.delete_view(self)
        DeviceInfo.create_view(self)
        File.create_view(self)


class Attributes(GarminDB.Base, HealthDB.KeyValueObject):
    """Object representing genertic key-value data from a Garmin device."""

    __tablename__ = 'attributes'
    table_version = 1

    @classmethod
    def measurements_type(cls, db):
        """Return the database units type (metric, statute, etc)."""
        return Fit.field_enums.DisplayMeasure.from_string(cls.get(db, 'measurement_system'))

    @classmethod
    def measurements_type_metric(cls, db):
        """Return True if the database units are metric."""
        return (cls.measurements_type(db) == Fit.field_enums.DisplayMeasure.metric)


class Device(GarminDB.Base, HealthDB.DBObject):
    """Class representing a Garmin device."""

    __tablename__ = 'devices'
    table_version = 3
    unknown_device_serial_number = 9999999999

    Manufacturer = HealthDB.derived_enum.derive('Manufacturer', Fit.field_enums.Manufacturer, {'Microsoft' : 100001, 'Unknown': 100000})

    serial_number = Column(Integer, primary_key=True)
    timestamp = Column(DateTime)
    manufacturer = Column(Enum(Manufacturer))
    product = Column(String)
    hardware_version = Column(String)

    time_col_name = 'timestamp'
    match_col_names = ['serial_number']

    @property
    def product_as_enum(self):
        """Convert the product attribute form a string to an enum and return it."""
        return Fit.field_enums.product_enum(self.manufacturer, self.product)

    @classmethod
    def get(cls, db, serial_number):
        """Return a device entry given the device's serial number."""
        return cls.find_one(db, {'serial_number' : serial_number})

    @classmethod
    def local_device_serial_number(cls, serial_number, device_type):
        """Return a synthetic serial number for a sub device composed of the parent's serial number and the sub device type."""
        return '%s%06d' % (serial_number, device_type.value)


class DeviceInfo(GarminDB.Base, HealthDB.DBObject):
    """Class representing a Garmin device info message from a FIT file."""

    __tablename__ = 'device_info'
    table_version = 2
    view_version = 4

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    file_id = Column(String, ForeignKey('files.id'))
    serial_number = Column(Integer, ForeignKey('devices.serial_number'), nullable=False)
    device_type = Column(String)
    software_version = Column(String)
    cum_operating_time = Column(Time, nullable=False, default=datetime.time.min)
    battery_voltage = Column(Float)

    time_col_name = 'timestamp'
    match_col_names = ['timestamp', 'serial_number', 'device_type']

    @classmethod
    def create_view(cls, db):
        """Create a databse view that presents the device info data in a more user friendly way."""
        cls.create_join_view(db, cls._get_default_view_name(),
            [
                cls.timestamp.label('timestamp'),
                cls.file_id.label('file_id'),
                cls.serial_number.label('serial_number'),
                cls.device_type.label('device_type'),
                cls.software_version.label('software_version'),
                Device.manufacturer.label('manufacturer'),
                Device.product.label('product'),
                Device.hardware_version.label('hardware_version')
            ],
            Device, cls.timestamp.desc())


class File(GarminDB.Base, HealthDB.DBObject):
    """Class representing a data file."""

    __tablename__ = 'files'
    table_version = 3
    view_version = 4

    fit_file_types_prefix = 'fit_'
    FileType = HealthDB.derived_enum.derive('FileType', Fit.field_enums.FileType, {'tcx' : 100001, 'gpx' : 100002}, fit_file_types_prefix)

    id = Column(String, primary_key=True)
    name = Column(String, unique=True)
    type = Column(Enum(FileType), nullable=False)
    serial_number = Column(Integer, ForeignKey('devices.serial_number'))

    match_col_names = ['name']

    @classmethod
    def _get_id(cls, session, pathname):
        """Return the id of a file given it's pathname."""
        return cls._find_id(session, {'name' : os.path.basename(pathname)})

    @classmethod
    def get_id(cls, db, pathname):
        """Return the id of a file given it's pathname."""
        return cls.find_id(db, {'name' : os.path.basename(pathname)})

    @classmethod
    def create_view(cls, db):
        """Create a databse view that presents the file data in a more user friendly way."""
        cls.create_multi_join_view(db, cls._get_default_view_name(),
            [
                DeviceInfo.timestamp.label('timestamp'),
                cls.id.label('activity_id'),
                cls.name.label('name'),
                cls.type.label('type'),
                Device.manufacturer.label('manufacturer'),
                Device.product.label('product'),
                Device.serial_number.label('serial_number')
            ],
            [(Device, File.serial_number == Device.serial_number), (DeviceInfo, File.id == DeviceInfo.file_id)],
            DeviceInfo.timestamp.desc())

    @classmethod
    def name_and_id_from_path(cls, pathname):
        """Return the name and id of a file given it's pathname."""
        name = os.path.basename(pathname)
        id = name.split('.')[0]
        return (id, name)

    @classmethod
    def id_from_path(cls, pathname):
        """Return the id of a file given it's pathname."""
        return os.path.basename(pathname).split('.')[0]


class Weight(GarminDB.Base, HealthDB.DBObject):
    """Class representing a weight entry."""

    __tablename__ = 'weight'
    table_version = 1

    day = Column(Date, primary_key=True)
    weight = Column(Float, nullable=False)

    time_col_name = 'day'

    @classmethod
    def get_stats(cls, session, start_ts, end_ts):
        stats = {
            'weight_avg' : cls._get_col_avg(session, cls.weight, start_ts, end_ts, True),
            'weight_min' : cls._get_col_min(session, cls.weight, start_ts, end_ts, True),
            'weight_max' : cls._get_col_max(session, cls.weight, start_ts, end_ts),
        }
        return stats


class Stress(GarminDB.Base, HealthDB.DBObject):
    """Class representing a stress reading."""

    __tablename__ = 'stress'
    table_version = 1

    timestamp = Column(DateTime, primary_key=True, unique=True)
    stress = Column(Integer, nullable=False)

    time_col_name = 'timestamp'

    @classmethod
    def get_stats(cls, session, start_ts, end_ts):
        stats = {
            'stress_avg' : cls._get_col_avg(session, cls.stress, start_ts, end_ts, True),
        }
        return stats


class Sleep(GarminDB.Base, HealthDB.DBObject):
    """Class representing a sleep session."""

    __tablename__ = 'sleep'
    table_version = 1

    day = Column(Date, primary_key=True)
    start = Column(DateTime)
    end = Column(DateTime)
    total_sleep = Column(Time, nullable=False, default=datetime.time.min)
    deep_sleep = Column(Time, nullable=False, default=datetime.time.min)
    light_sleep = Column(Time, nullable=False, default=datetime.time.min)
    rem_sleep = Column(Time, nullable=False, default=datetime.time.min)
    awake = Column(Time, nullable=False, default=datetime.time.min)

    time_col_name = 'day'

    @classmethod
    def get_stats(cls, session, start_ts, end_ts):
        return {
            'sleep_avg'     : cls._get_time_col_avg(session, cls.total_sleep, start_ts, end_ts),
            'sleep_min'     : cls._get_time_col_min(session, cls.total_sleep, start_ts, end_ts),
            'sleep_max'     : cls._get_time_col_max(session, cls.total_sleep, start_ts, end_ts),
            'rem_sleep_avg' : cls._get_time_col_avg(session, cls.rem_sleep, start_ts, end_ts),
            'rem_sleep_min' : cls._get_time_col_min(session, cls.rem_sleep, start_ts, end_ts),
            'rem_sleep_max' : cls._get_time_col_max(session, cls.rem_sleep, start_ts, end_ts),
        }


class SleepEvents(GarminDB.Base, HealthDB.DBObject):
    __tablename__ = 'sleep_events'
    table_version = 1

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, unique=True)
    event = Column(String)
    duration = Column(Time, nullable=False, default=datetime.time.min)

    time_col_name = 'timestamp'

    @classmethod
    def get_wake_time(cls, db, day_date):
        day_start_ts = datetime.datetime.combine(day_date, datetime.time.min)
        day_stop_ts = datetime.datetime.combine(day_date, datetime.time.max)
        values = cls.get_col_values(db, cls.timestamp, cls.event, 'wake_time', day_start_ts, day_stop_ts)
        if len(values) > 0:
            return values[0][0]


class RestingHeartRate(GarminDB.Base, HealthDB.DBObject):
    """Class representing a daily resting heart rate reading."""

    __tablename__ = 'resting_hr'
    table_version = 1

    day = Column(Date, primary_key=True)
    resting_heart_rate = Column(Float)

    time_col_name = 'day'

    @classmethod
    def get_stats(cls, session, start_ts, end_ts):
        stats = {
            'rhr_avg' : cls._get_col_avg(session, cls.resting_heart_rate, start_ts, end_ts, True),
            'rhr_min' : cls._get_col_min(session, cls.resting_heart_rate, start_ts, end_ts, True),
            'rhr_max' : cls._get_col_max(session, cls.resting_heart_rate, start_ts, end_ts),
        }
        return stats


class DailySummary(GarminDB.Base, HealthDB.DBObject):
    """Class representing a Garmin daily summary."""

    __tablename__ = 'daily_summary'
    table_version = 1

    day = Column(Date, primary_key=True)
    hr_min = Column(Integer)
    hr_max = Column(Integer)
    rhr = Column(Integer)
    stress_avg = Column(Integer)
    step_goal = Column(Integer)
    steps = Column(Integer)
    moderate_activity_time = Column(Time, nullable=False, default=datetime.time.min)
    vigorous_activity_time = Column(Time, nullable=False, default=datetime.time.min)
    intensity_time_goal = Column(Time, nullable=False, default=datetime.time.min)
    floors_up = Column(Float)
    floors_down = Column(Float)
    floors_goal = Column(Float)
    distance = Column(Float)
    calories_goal = Column(Integer)
    calories_total = Column(Integer)
    calories_bmr = Column(Integer)
    calories_active = Column(Integer)
    calories_consumed = Column(Integer)
    description = Column(String)

    time_col_name = 'day'

    @hybrid_property
    def intensity_time(self):
        """Return intensity_time computed from moderate_activity_time and vigorous_activity_time."""
        return Fit.conversions.add_time(self.moderate_activity_time, self.vigorous_activity_time, 2)

    @intensity_time.expression
    def intensity_time(cls):
        """Return intensity_time computed from moderate_activity_time and vigorous_activity_time."""
        return cls.time_from_secs(2 * cls.secs_from_time(cls.vigorous_activity_time) + cls.secs_from_time(cls.moderate_activity_time))

    @hybrid_property
    def intensity_time_goal_percent(self):
        """Return the percentage of intensity time goal achieved."""
        if self.intensity_time is not None and self.intensity_time_goal is not None:
            return (conversions.time_to_secs(self.intensity_time) * 100) / conversions.time_to_secs(self.intensity_time_goal)
        return 0.0

    @intensity_time_goal_percent.expression
    def intensity_time_goal_percent(cls):
        """Return the percentage of intensity time goal achieved."""
        return func.round((cls.secs_from_time(cls.intensity_time) * 100) / cls.secs_from_time(cls.intensity_time_goal))

    @hybrid_property
    def steps_goal_percent(self):
        """Return the percentage of steps goal achieved."""
        if self.steps is not None and self.step_goal is not None:
            return (self.steps * 100) / self.step_goal
        return 0.0

    @steps_goal_percent.expression
    def steps_goal_percent(cls):
        """Return the percentage of steps goal achieved."""
        return func.round((cls.steps * 100) / cls.step_goal)

    @hybrid_property
    def floors_goal_percent(self):
        """Return the percentage of floors goal achieved."""
        if self.floors_up is not None and self.floors_goal is not None:
            return (self.floors_up * 100) / self.floors_goal
        return 0.0

    @floors_goal_percent.expression
    def floors_goal_percent(cls):
        """Return the percentage of floors goal achieved."""
        return func.round((cls.floors_up * 100) / cls.floors_goal)

    @classmethod
    def get_stats(cls, session, start_ts, end_ts):
        return {
            'rhr_avg'                   : cls._get_col_avg(session, cls.rhr, start_ts, end_ts),
            'rhr_min'                   : cls._get_col_min(session, cls.rhr, start_ts, end_ts),
            'rhr_max'                   : cls._get_col_max(session, cls.rhr, start_ts, end_ts),
            'stress_avg'                : cls._get_col_avg(session, cls.stress_avg, start_ts, end_ts),
            'steps'                     : cls._get_col_sum(session, cls.steps, start_ts, end_ts),
            'steps_goal'                : cls._get_col_sum(session, cls.step_goal, start_ts, end_ts),
            'floors'                    : cls._get_col_sum(session, cls.floors_up, start_ts, end_ts),
            'floors_goal'               : cls._get_col_sum(session, cls.floors_goal, start_ts, end_ts),
            'calories_goal'             : cls._get_col_avg(session, cls.calories_goal, start_ts, end_ts),
            'intensity_time'            : cls._get_time_col_sum(session, cls.intensity_time, start_ts, end_ts),
            'moderate_activity_time'    : cls._get_time_col_sum(session, cls.moderate_activity_time, start_ts, end_ts),
            'vigorous_activity_time'    : cls._get_time_col_sum(session, cls.vigorous_activity_time, start_ts, end_ts),
            'intensity_time_goal'       : cls._get_time_col_avg(session, cls.intensity_time_goal, start_ts, end_ts),
            'calories_avg'              : cls._get_col_avg(session, cls.calories_total, start_ts, end_ts),
            'calories_bmr_avg'          : cls._get_col_avg(session, cls.calories_bmr, start_ts, end_ts),
            'calories_active_avg'       : cls._get_col_avg(session, cls.calories_active, start_ts, end_ts),
        }

    @classmethod
    def get_daily_stats(cls, session, day_ts):
        stats = cls.get_stats(session, day_ts, day_ts + datetime.timedelta(1))
        # intensity_time_goal is a weekly goal, so the daily value is 1/7 of the weekly goal
        stats['intensity_time_goal'] = cls.time_from_secs(cls.secs_from_time(stats['intensity_time_goal']) / 7)
        stats['day'] = day_ts
        return stats

    @classmethod
    def get_monthly_stats(cls, session, first_day_ts, last_day_ts):
        stats = cls.get_stats(session, first_day_ts, last_day_ts)
        # intensity time is a weekly goal, so sum up the weekly average values
        first_week_end = first_day_ts + datetime.timedelta(7)
        second_week_end = first_day_ts + datetime.timedelta(14)
        third_week_end = first_day_ts + datetime.timedelta(21)
        fourth_week_end = first_day_ts + datetime.timedelta(28)
        stats['intensity_time_goal'] = Fit.conversions.add_time(
            Fit.conversions.add_time(
                cls._get_time_col_avg(session, cls.intensity_time_goal, first_day_ts, first_week_end),
                cls._get_time_col_avg(session, cls.intensity_time_goal, first_week_end, second_week_end)
            ),
            Fit.conversions.add_time(
                cls._get_time_col_avg(session, cls.intensity_time_goal, second_week_end, third_week_end),
                cls._get_time_col_avg(session, cls.intensity_time_goal, third_week_end, fourth_week_end)
            )
        )
        stats['first_day'] = first_day_ts
        return stats


class DailyExtraData(GarminDB.Base, ExtraData):
    __tablename__ = 'daily_extra_data'
    table_version = 1

    day = Column(Date, primary_key=True)

    time_col_name = 'day'

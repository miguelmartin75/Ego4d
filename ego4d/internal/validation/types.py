# pyre-strict
import csv
import json
import os
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ego4d.internal.s3 import ls_relative

from iopath.common.file_io import PathManager
from iopath.common.s3 import S3PathHandler

pathmgr = PathManager()
pathmgr.register_handler(S3PathHandler(profile="default"))


DEFAULT_DATE_FORMAT_STR = "%Y-%m-%d %H:%M:%S"


class ErrorLevel(Enum):
    WARN = 0
    ERROR = 1


@dataclass
class Error:
    level: ErrorLevel
    uid: str
    type: str
    description: str


@dataclass
class Device:
    device_id: int
    name: str


@dataclass
class ComponentType:
    component_type_id: int
    name: str


@dataclass
class Scenario:
    scenario_id: int
    name: str
    included_in_release_1: bool
    is_ad_hoc: bool


@dataclass
class VideoMetadata:
    university_video_id: str
    university_video_folder_path: str
    number_video_components: int
    start_date_recorded_utc: datetime
    recording_participant_id: str
    device_id: int
    video_device_settings: dict
    physical_setting_id: str
    video_scenario_ids: List[int]


@dataclass
class VideoComponentFile:
    university_video_id: str
    video_component_relative_path: str
    component_index: int
    is_redacted: bool
    start_date_recorded_utc: datetime
    compression_settings: dict
    includes_audio: bool
    component_metadata: dict
    deidentification_metadata: dict


@dataclass
class AuxiliaryVideoComponentDataFile:
    university_video_id: str
    component_index: int
    component_type_id: int
    video_component_relative_path: str


@dataclass
class Particpant:
    participant_id: str
    participant_metadata: dict


@dataclass
class SynchronizedVideos:
    video_grouping_id: str
    synchronization_metadata: dict
    associated_videos: dict


@dataclass
class PhysicalSetting:
    setting_id: str
    name: str
    associated_matterport_scan_path: str


@dataclass
class Annotations:
    university_video_id: str
    start_seconds: float
    end_seconds: float
    annotation_data: dict


@dataclass
class StandardMetadata:
    devices: Dict[str, Device]
    component_types: Dict[str, ComponentType]
    scenarios: Dict[str, Scenario]


@dataclass
class Manifest:
    videos: Dict[str, VideoMetadata]
    video_components: Dict[str, List[VideoComponentFile]]
    aux_components: Dict[str, List[AuxiliaryVideoComponentDataFile]]
    participants: Dict[str, Particpant]
    sync_videos: Dict[str, SynchronizedVideos]
    physical_setting: Dict[str, PhysicalSetting]
    annotations: Dict[str, List[Annotations]]


# new EgoExo types


@dataclass
class CaptureMetadataEgoExo:
    university_capture_id: str
    university_video_folder_path: str
    number_videos: int
    number_takes: int
    post_surveys_relative_path: str
    physical_setting_id: int
    start_date_recorded_utc: datetime
    additional_metadata: dict


@dataclass
class TakeMetadataEgoExo:
    university_capture_id: str
    take_id: str
    scenario_id: int
    is_narrated: bool
    is_dropped: bool
    take_start_seconds_aria: float
    object_ids: List[str]
    recording_participant_id: str
    additional_metadata: dict


@dataclass
class VideoMetadataEgoExo:
    university_capture_id: str
    university_video_id: str
    number_video_components: int
    is_ego: str
    has_walkaround: str
    includes_audio: str
    device_type: int
    device_id: str
    video_device_settings: dict
    additional_metadata: dict
    is_redacted: bool


@dataclass
class VideoComponentFileEgoExo:
    university_capture_id: str
    university_video_id: str
    video_component_relative_path: str
    component_index: int
    is_redacted: bool


@dataclass
class ColmapMetadataEgoExo:
    university_capture_id: str
    colmap_configuration_id: str
    config_relative_path: str
    colmap_ran: bool
    was_inspected: bool
    is_final_configuration: bool
    version: str
    notes: str


@dataclass
class ObjectMetadataEgoExo:
    university_object_id: str
    object_name: str
    object_relative_path: str
    physical_setting_id: str
    additional_metadata: dict


@dataclass
class ParticipantMetadataEgoExo:
    participant_id: str
    participant_metadata: dict
    collection_date: datetime
    pre_survey_data: dict
    participant_metadata: dict


@dataclass
class PhysicalSettingEgoExo:
    setting_id: str
    name: str


@dataclass
class ExtraDataEgoExo:
    university_capture_id: str
    take_id: str
    annotation_data: dict


@dataclass
class ScenarioEgoExo:
    scenario_id: int
    name: str


@dataclass
class StandardMetadataEgoExo:
    devices: Dict[str, Device]
    scenarios: Dict[str, ScenarioEgoExo]


@dataclass
class ManifestEgoExo:
    captures: Dict[str, CaptureMetadataEgoExo]  # by capture id
    takes: Dict[str, List[TakeMetadataEgoExo]]  # by capture id
    videos: Dict[str, List[VideoMetadataEgoExo]]  # by capture id
    video_components: Dict[str, List[VideoComponentFileEgoExo]]  # by video id
    colmap: Optional[Dict[str, List[ColmapMetadataEgoExo]]]  # by capture id
    physical_setting: Dict[str, PhysicalSettingEgoExo]  # by setting id
    objects: Optional[Dict[str, ObjectMetadataEgoExo]]  # by object id
    participants: Optional[Dict[str, ParticipantMetadataEgoExo]]  # by participant id
    extra_data: Optional[List[ExtraDataEgoExo]]


def default_decode(value: str, datatype: type) -> Any:
    if datatype in (dict, defaultdict):
        if len(value) == 0:
            return {}
        return json.loads(value)
    elif datatype == list:
        if len(value) == 0:
            return []
        return json.loads(value)
    elif datatype == datetime:
        return (
            datetime.strptime(value.split(".")[0], DEFAULT_DATE_FORMAT_STR)
            if len(value) > 0
            else datetime(1900, 1, 1)
        )
    elif datatype in (int, float, str, bool):
        if len(value) == 0:
            return None
        return datatype(value)


def load_dataclass_dict_from_csv(
    input_csv_file_path: str,
    dataclass_class: type,
    dict_key_field: str,
    unique_per_key: bool,
    default_decode_fn: Callable[[str, type], Any] = default_decode,
) -> Dict[Any, List[Any]]:
    """
    Args:
        input_csv_file_path (str): File path of the csv to read from
        dataclass_class (type): The dataclass to read each row into.
        dict_key_field (str): The field of 'dataclass_class' to use as
            the dictionary key.
        list_per_key (bool) = False: If the output data structure
        contains a list of dataclass objects per key, rather than a
        single unique dataclass object.

    Returns:
        Dict[Any, Union[Any, List[Any]] mapping from the dataclass
        value at attr = dict_key_field to either:

        if 'list_per_key', a list of all dataclass objects that
        have equal values at attr = dict_key_field, equal to the key

        if not 'list_per_key', the unique dataclass object
        for which the value at attr = dict_key_field is equal to the key

    Raises:
        AssertionError: if not 'list_per_key' and there are
        dataclass objects with equal values at attr = dict_key_field
    """

    output = defaultdict(list)
    with pathmgr.open(input_csv_file_path) as csvfile:
        reader = csv.reader(csvfile, delimiter=",", quotechar='"')  # pyre-ignore
        column_index = {header: i for i, header in enumerate(next(reader))}

        field_name_to_metadata = {
            f.name: {
                "decode_fn": (
                    f.metadata["csv_decode_fn"]
                    if "csv_decode_fn" in f.metadata
                    else default_decode_fn
                ),
                "column_index": column_index.get(f.name, None),
                "type": f.type,
            }
            for f in fields(dataclass_class)
        }
        csv_names = set(column_index.keys())
        dn_names = set(field_name_to_metadata.keys())
        if csv_names != dn_names:
            missing_str = "\n".join([f"- {x}" for x in (dn_names - csv_names)])
            additional_str = "\n".join([f"- {x}" for x in (csv_names - dn_names)])
            raise AssertionError(
                f"""
Missing fields from CSV:
{missing_str}
Additional fields in CSV:
{additional_str}
"""
            )

        for line in reader:
            obj = dataclass_class(
                **{
                    name: meta["decode_fn"](
                        line[meta["column_index"]],
                        meta["type"],
                    )
                    for name, meta in field_name_to_metadata.items()
                }
            )
            dict_key = getattr(obj, dict_key_field)
            output[dict_key].append(obj)
            if unique_per_key:
                if len(output[dict_key]) != 1:
                    raise AssertionError(
                        f"Multiple entries for same PK: {dict_key_field}: {dict_key}"
                    )
    return output


def load_standard_metadata_files(
    standard_metadata_folder: str,
) -> StandardMetadata:
    if not pathmgr.exists(standard_metadata_folder):
        raise AssertionError(f"{standard_metadata_folder} does not exist")
    available_files = ls_relative(standard_metadata_folder, pathmgr)

    file_name = "device.csv"
    if file_name not in available_files:
        raise AssertionError(
            f"required file {file_name} not found in " f"{standard_metadata_folder}"
        )

    file_path = os.path.join(standard_metadata_folder, file_name)
    devices = load_dataclass_dict_from_csv(
        file_path,
        Device,
        "device_id",
        unique_per_key=True,
    )

    file_name = "component_type.csv"
    if file_name not in available_files:
        raise AssertionError(
            f"required file {file_name} not found in " f"{standard_metadata_folder}"
        )

    file_path = os.path.join(standard_metadata_folder, file_name)
    component_types = load_dataclass_dict_from_csv(
        file_path,
        ComponentType,
        "component_type_id",
        unique_per_key=True,
    )

    file_name = "scenario.csv"
    if file_name not in available_files:
        raise AssertionError(
            f"required file {file_name} not found in " f"{standard_metadata_folder}"
        )
    file_path = os.path.join(standard_metadata_folder, file_name)
    scenarios = load_dataclass_dict_from_csv(
        file_path,
        Scenario,
        "scenario_id",
        unique_per_key=True,
    )

    # TODO: fixme to updated stats
    assert len(scenarios) > 0
    assert len(devices) > 0
    assert len(component_types) > 0

    return StandardMetadata(
        devices={k: vs[0] for k, vs in devices.items()},
        component_types={k: vs[0] for k, vs in component_types.items()},
        scenarios={k: vs[0] for k, vs in scenarios.items()},
    )


def load_standard_metadata_files_egoexo(
    standard_metadata_folder: str,
) -> StandardMetadataEgoExo:
    if not pathmgr.exists(standard_metadata_folder):
        raise AssertionError(f"{standard_metadata_folder} does not exist")
    available_files = ls_relative(standard_metadata_folder, pathmgr)

    file_name = "device.csv"
    if file_name not in available_files:
        raise AssertionError(
            f"required file {file_name} not found in {standard_metadata_folder}"
        )

    file_path = os.path.join(standard_metadata_folder, file_name)
    devices = load_dataclass_dict_from_csv(
        file_path,
        Device,
        "device_id",
        unique_per_key=True,
    )

    file_name = "scenario.csv"
    if file_name not in available_files:
        raise AssertionError(
            f"required file {file_name} not found in {standard_metadata_folder}"
        )
    file_path = os.path.join(standard_metadata_folder, file_name)
    scenarios = load_dataclass_dict_from_csv(
        file_path,
        ScenarioEgoExo,
        "scenario_id",
        unique_per_key=True,
    )

    # TODO: fixme to updated stats
    assert len(scenarios) > 0
    assert len(devices) > 0

    return StandardMetadataEgoExo(
        devices={k: vs[0] for k, vs in devices.items()},
        scenarios={k: vs[0] for k, vs in scenarios.items()},
    )


def load_egoexo_manifest(manifest_dir: str) -> ManifestEgoExo:
    available_files = ls_relative(manifest_dir, pathmgr)

    def _check_file_exists():
        if file_name not in available_files:
            raise AssertionError(
                f"required file {file_name} not found in {manifest_dir}"
            )

    file_name = "capture_metadata.csv"
    file_path = os.path.join(manifest_dir, file_name)
    _check_file_exists()
    capture_metadata = load_dataclass_dict_from_csv(
        file_path,
        CaptureMetadataEgoExo,
        "university_capture_id",
        unique_per_key=True,
    )

    file_name = "take_metadata.csv"
    file_path = os.path.join(manifest_dir, file_name)
    _check_file_exists()
    take_metadata = load_dataclass_dict_from_csv(
        file_path,
        TakeMetadataEgoExo,
        "university_capture_id",
        unique_per_key=False,
    )

    file_name = "video_metadata.csv"
    file_path = os.path.join(manifest_dir, file_name)
    _check_file_exists()
    video_metadata = load_dataclass_dict_from_csv(
        file_path,
        VideoMetadataEgoExo,
        "university_capture_id",
        unique_per_key=False,
    )

    file_name = "video_component_file.csv"
    file_path = os.path.join(manifest_dir, file_name)
    _check_file_exists()
    video_component_metadata = load_dataclass_dict_from_csv(
        file_path,
        VideoComponentFileEgoExo,
        "university_capture_id",
        unique_per_key=False,
    )

    file_name = "colmap_metadata.csv"
    file_path = os.path.join(manifest_dir, file_name)
    colmap_metadata = None
    if file_name in available_files:
        colmap_metadata = load_dataclass_dict_from_csv(
            file_path,
            ColmapMetadataEgoExo,
            "university_capture_id",
            unique_per_key=False,
        )

    file_name = "object_metadata.csv"
    file_path = os.path.join(manifest_dir, file_name)
    object_metadata = None
    if file_name in available_files:
        object_metadata = load_dataclass_dict_from_csv(
            file_path,
            ObjectMetadataEgoExo,
            "university_object_id",
            unique_per_key=True,
        )

    file_name = "physical_setting.csv"
    file_path = os.path.join(manifest_dir, file_name)
    physical_setting = None
    if file_name in available_files:
        physical_setting = load_dataclass_dict_from_csv(
            file_path,
            PhysicalSettingEgoExo,
            "setting_id",
            unique_per_key=True,
        )

    file_name = "participant_metadata.csv"
    file_path = os.path.join(manifest_dir, file_name)
    participant_metadata = None
    if file_name in available_files:
        participant_metadata = load_dataclass_dict_from_csv(
            file_path,
            ParticipantMetadataEgoExo,
            "participant_id",
            unique_per_key=True,
        )

    file_name = "extra_data.csv"
    file_path = os.path.join(manifest_dir, file_name)
    extra_data = None
    if file_name in available_files:
        extra_data = load_dataclass_dict_from_csv(
            file_path,
            ExtraDataEgoExo,
            "university_capture_id",
            unique_per_key=False,
        )

    return ManifestEgoExo(
        captures=capture_metadata,
        takes=take_metadata,
        videos=video_metadata,
        video_components=video_component_metadata,
        colmap=colmap_metadata,
        physical_setting=physical_setting,
        objects=object_metadata,
        participants=participant_metadata,
        extra_data=extra_data,
    )


def load_manifest(manifest_dir: str) -> Manifest:
    available_files = ls_relative(manifest_dir, pathmgr)

    def _check_file_exists():
        if file_name not in available_files:
            raise AssertionError(
                f"required file {file_name} not found in {manifest_dir}"
            )

    file_name = "video_metadata.csv"
    file_path = os.path.join(manifest_dir, file_name)
    _check_file_exists()
    video_metadata_dict = load_dataclass_dict_from_csv(
        file_path,
        VideoMetadata,
        "university_video_id",
        unique_per_key=True,
    )

    # Load video_component_file.csv
    file_name = "video_component_file.csv"
    file_path = os.path.join(manifest_dir, file_name)
    _check_file_exists()
    video_components_dict = load_dataclass_dict_from_csv(
        file_path,
        VideoComponentFile,
        "university_video_id",
        unique_per_key=False,
    )

    # Load optional files
    # Load auxiliary_video_component_data_file.csv, if available
    file_name = "auxiliary_video_component_data_file.csv"
    auxiliary_video_component_dict = {}
    if file_name in available_files:
        file_path = os.path.join(manifest_dir, file_name)
        auxiliary_video_component_dict = load_dataclass_dict_from_csv(
            file_path,
            AuxiliaryVideoComponentDataFile,
            "university_video_id",
            unique_per_key=False,
        )

    # Load participant.csv, if available
    participant_dict = {}
    for file_name in [
        "participant_data.csv",
        "participant.csv",
        "participant_metadata.csv",
    ]:
        if file_name in available_files:
            file_path = os.path.join(manifest_dir, file_name)
            participant_dict = load_dataclass_dict_from_csv(
                file_path,
                Particpant,
                "participant_id",
                unique_per_key=True,
            )
            break

    # Load synchronized_videos.csv, if available
    file_name = "synchronized_videos.csv"
    synchronized_video_dict = {}
    if file_name in available_files:
        file_path = os.path.join(manifest_dir, file_name)
        synchronized_video_dict = load_dataclass_dict_from_csv(
            file_path,
            SynchronizedVideos,
            "video_grouping_id",
            unique_per_key=True,
        )

    # Load physical_setting.csv, if available
    file_name = "physical_setting.csv"
    physical_setting_dict = {}
    if file_name in available_files:
        file_path = os.path.join(manifest_dir, file_name)
        physical_setting_dict = load_dataclass_dict_from_csv(
            file_path,
            PhysicalSetting,
            "setting_id",
            unique_per_key=True,
        )

    # Load annotations.csv, if available
    file_name = "annotations.csv"
    annotations_dict = {}
    if file_name in available_files:
        file_path = os.path.join(manifest_dir, file_name)
        annotations_dict = load_dataclass_dict_from_csv(
            file_path,
            Annotations,
            "university_video_id",
            unique_per_key=False,
        )

    return Manifest(
        # unique keys
        videos={k: vs[0] for k, vs in video_metadata_dict.items()},
        participants={k: vs[0] for k, vs in participant_dict.items()},
        sync_videos={k: vs[0] for k, vs in synchronized_video_dict.items()},
        physical_setting={k: vs[0] for k, vs in physical_setting_dict.items()},
        # non-unique keys
        video_components=video_components_dict,
        aux_components=auxiliary_video_component_dict,
        annotations=annotations_dict,
    )


def load_released_video_files(
    released_video_path: Optional[str],
) -> Optional[Dict[str, List[str]]]:
    # TODO: changeme
    if released_video_path is None:
        return None

    with pathmgr.open(released_video_path) as csvfile:
        released_videos = defaultdict(list)
        reader = csv.reader(csvfile, delimiter=",", quotechar='"')
        _ = next(reader)  # skip header
        for line in reader:
            released_videos[line[2]].append(line[0])
    return released_videos

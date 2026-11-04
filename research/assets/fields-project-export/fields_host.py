# IronPython 2.7 resource. No solver Run/Calculate, no startup/profile changes.
import os
import json
import hashlib
import shutil
import traceback
from decimal import Decimal
from System import Double, Object, Func, String
from System.Diagnostics import Process
from DeltaShell.Plugins.FMSuite.FlowFM.Model import WaterFlowFMModel
from DeltaShell.Plugins.FMSuite.FlowFM.IO.ImportExport.Exporters import FMModelFileExporter

root = os.environ['E014_EXPORT_ROOT']
nonce = os.environ['E014_EXPORT_NONCE']
with open(os.path.join(root, 'request.json')) as stream:
    request = json.load(stream)
contract_path = os.path.join(fields_bundle, 'runtime', 'fields-contract.json')
with open(contract_path) as stream:
    contract = json.load(stream)
assert contract['kind'] == 'E014_f34_typed_property_export'
assert request['kind'] == contract['kind']
assert request['nonce'] == nonce and request['engine_execution'] is False


def sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def inventory(folder):
    result = {}
    for parent, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(parent, name)
            result[os.path.relpath(path, folder).replace('\\', '/')] = {'sha256': sha(path), 'bytes': os.path.getsize(path)}
    return result


def local(relative):
    path = os.path.abspath(os.path.join(root, relative))
    assert path.lower().startswith(os.path.abspath(root).lower() + os.sep)
    return path


def fresh_dir(relative):
    path = local(relative)
    assert not os.path.exists(path)
    os.makedirs(path)
    return path


def number(value):
    return Decimal(str(value).lower().replace('d', 'e'))


def exported_fields(path):
    result = {}; section = ''
    with open(path) as stream:
        for line in stream:
            text = line.split('#', 1)[0].strip()
            if text.startswith('[') and text.endswith(']'):
                section = text[1:-1].strip().lower()
            elif text and not text.startswith(';') and '=' in text:
                key, value = text.split('=', 1)
                key = section + '/' + key.strip().lower()
                assert key not in result, 'Duplicate exported MDU key: ' + key
                result[key] = value.strip()
    return result


def baseline(model, source):
    expected = dict(contract['baseline'])
    if source == 'manning':
        expected['physics/uniffricttype'] = '1'
        expected['physics/uniffrictcoef'] = '0.023'
    for key, value in expected.items():
        prop = model.ModelDefinition.GetModelProperty(key.split('/')[1])
        assert prop is not None and number(prop.Value) == number(value), 'Unexpected live baseline ' + key


def manning_export(path):
    actual = exported_fields(path)
    assert number(actual['physics/uniffricttype']) == Decimal('1'), 'Exported control is NOT Manning'
    assert number(actual['physics/uniffrictcoef']) == Decimal('0.023'), 'Wrong exported Manning control coefficient'


def model_in(project):
    items = list(project.RootFolder.Items)
    assert len(items) == 1, 'Expected only one root item'
    model = items[0]
    assert str(model.GetType().FullName) == 'DeltaShell.Plugins.FMSuite.FlowFM.Model.WaterFlowFMModel'
    assert str(model.Name).lower() == 'f34'
    assert model.Grid.Vertices.Count == 258 and model.Grid.Edges.Count == 479
    return model


def assembly_info(assembly):
    return {'full_name': str(assembly.FullName), 'location': str(assembly.Location), 'sha256': sha(str(assembly.Location))}


def property_info(model, key, unit):
    definition = contract['schema_provenance']['definitions'][key]
    prop = model.ModelDefinition.GetModelProperty(key.split('/')[1])
    assert prop is not None
    schema = prop.PropertyDefinition
    section_key = str(schema.FileSectionName).lower() + '/' + str(schema.MduPropertyName).lower()
    assert section_key == key, 'Wrong actual property owner/key'
    assert str(prop.GetType().FullName) == definition['owner']
    assert str(schema.GetType().FullName) == definition['definition']
    assert str(schema.DataType.FullName) == 'System.Double'
    assert str(prop.Value.GetType().FullName) == 'System.Double'
    assert str(schema.Unit).strip() == definition['unit_metadata'], 'Actual unit metadata differs from installed CSV'
    assert schema.IsDefinedInSchema and not schema.ModelFileOnly
    selected = {'geometry/waterlevini': 'm', 'time/dtmax': 's', 'physics/uniffrictcoef': 's m-1/3'}[key]
    assert unit == selected, 'Wrong physical unit (protocol guard)'
    if key == 'physics/uniffrictcoef':
        assert number(model.ModelDefinition.GetModelProperty('UnifFrictType').Value) == Decimal('1'), 'Chezy must NOT be edited as Manning'
    value_property = prop.GetType().GetProperty('Value')
    assert str(value_property.DeclaringType.FullName) == definition['value_declaring_type']
    info = dict((name, definition[name]) for name in ('owner', 'definition', 'value_declaring_type', 'data_type', 'owner_path', 'unit_metadata'))
    info.update(section_key=section_key, runtime_value_type=str(prop.Value.GetType().FullName), unit=unit,
                schema_unit_raw=str(schema.Unit), category=str(schema.Category), subcategory=str(schema.SubCategory),
                caption=str(schema.Caption), model_property_only=bool(schema.ModelFileOnly),
                owner_assembly=assembly_info(prop.GetType().Assembly), value_assembly=assembly_info(value_property.DeclaringType.Assembly))
    csv_path = os.path.join(os.path.dirname(str(prop.GetType().Assembly.Location)), 'CsvFiles', 'dflowfm-properties.csv')
    info['schema_file'] = {'path': csv_path, 'sha256': sha(csv_path)}
    files = contract['schema_provenance']['files']
    flow = 'plugins/DeltaShell.Plugins.FMSuite.FlowFM/DeltaShell.Plugins.FMSuite.FlowFM.dll'
    common = 'plugins/DeltaShell.Plugins.FMSuite.Common/DeltaShell.Plugins.FMSuite.Common.dll'
    assert info['owner_assembly']['sha256'] == files[flow]['sha256']
    assert info['value_assembly']['sha256'] == files[common]['sha256']
    assert info['schema_file']['sha256'] == files['plugins/DeltaShell.Plugins.FMSuite.FlowFM/CsvFiles/dflowfm-properties.csv']['sha256']
    return prop, info


def export(model, relative):
    folder = fresh_dir(relative)
    path = os.path.join(folder, 'f34.mdu')
    assert bool(FMModelFileExporter().Export(model, path)) and os.path.isfile(path)
    assert len(inventory(folder)) == 10, 'Expected ten files from actual exporter'
    return path


def copy_project(source, relative):
    folder = fresh_dir(relative)
    target = os.path.join(folder, os.path.basename(source))
    shutil.copyfile(source, target)
    shutil.copytree(source + '_data', target + '_data')
    return target


def rejected(call):
    try:
        call()
    except Exception as error:
        return {'passed': True, 'exception_type': str(error.GetType().FullName) if hasattr(error, 'GetType') else str(type(error)), 'message': str(error)}
    raise AssertionError('Expected rejection did not occur')


record = {'kind': contract['kind'], 'nonce': nonce, 'success': False, 'project_closed': False,
          'contract_sha256': sha(contract_path), 'engine_execution': False,
          'bundle_sha256': request['bundle_sha256'], 'guest_lifecycle_sha256': request['guest_lifecycle_sha256'],
          'trigger': 'console --run-file; no GUI click parity claimed', 'pid': Process.GetCurrentProcess().Id,
          'cases': {}, 'controls': {}, 'source_unchanged': False}
opened = False
original = local(request['project'])
before_original = (sha(original), inventory(original + '_data'))
try:
    with open(os.path.join(fields_bundle, 'bundle.json')) as stream:
        manifest = json.load(stream)
    assert manifest['kind'] == contract['kind'] and manifest['nonce'] == nonce
    assert sha(os.path.join(fields_bundle, 'bundle.json')) == request['bundle_sha256']
    lifecycle_json = json.dumps(manifest['guest_lifecycle'], sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    assert hashlib.sha256(lifecycle_json.encode('ascii')).hexdigest() == request['guest_lifecycle_sha256']
    # E014 owns its experiment settings BEFORE its first project operation.
    # Startup isolation is provided by the shared guest gate, not these settings.
    Application.SettingsManager.SetSetting('persistenceDefault', '.dsproj')
    Application.SettingsManager.SetSetting('useNewPersistence', 'false')
    assert Application.SettingsManager.GetSetting('persistenceDefault') == '.dsproj'
    assert Application.SettingsManager.GetSetting('useNewPersistence') == 'false'
    # Mandatory separate authored Manning import/save/reopen. Never apply law
    # changes to any copied original Chezy project in this single-field replay.
    work = fresh_dir('manning-prerequisite/work')
    seed_folder = fresh_dir('manning-prerequisite/project')
    seed = os.path.join(seed_folder, 'manning-control.dsproj')
    project = Application.ProjectService.CreateProject(); opened = True
    model = WaterFlowFMModel()
    model.WorkingDirectoryPathFunc = Func[String](lambda: work)
    model.ImportFromMdu(os.path.join(fields_bundle, 'fixtures', 'manning', 'f34.mdu'), True)
    project.RootFolder.Items.Add(model)
    baseline(model, 'manning')
    Application.ProjectService.SaveProjectAs(seed)
    manning_export(export(model, 'manning-prerequisite/exported'))
    Application.ProjectService.CloseProject(); opened = False
    project = Application.ProjectService.OpenProject(seed); opened = True
    model = model_in(project); baseline(model, 'manning')
    manning_export(export(model, 'manning-prerequisite/reopened'))
    Application.ProjectService.CloseProject(); opened = False
    record['manning_prerequisite'] = {'exported_law': '1', 'exported_coefficient': '0.023', 'reopened_law': '1', 'reopened_coefficient': '0.023', 'passed_before_any_coefficient_edit': True}
    for name in ('control', 'waterlevini', 'dtmax', 'manning-control', 'manning'):
        case = contract['cases'][name]
        source = original if case['source'] == 'chezy' else seed
        copied = copy_project(source, 'cases/' + name + '/input-project')
        before_copy = (sha(copied), inventory(copied + '_data'))
        project = Application.ProjectService.OpenProject(copied); opened = True
        model = model_in(project); baseline(model, case['source'])
        before_path = export(model, 'cases/' + name + '/before')
        if case['source'] == 'manning':
            manning_export(before_path)
        entry = {'source': case['source'], 'reopened': False}
        if name == 'control':
            prop, info = property_info(model, 'geometry/waterlevini', 'm')
            previous = number(prop.Value)
            control = rejected(lambda: prop.SetValueFromString('not-a-number'))
            control['mechanism'] = 'actual ModelProperty.SetValueFromString'
            assert control['exception_type'] == 'System.FormatException'
            assert number(prop.Value) == previous
            record['controls']['invalid_numeric'] = control
            record['controls']['wrong_unit'] = rejected(lambda: property_info(model, 'geometry/waterlevini', 's'))
            record['controls']['wrong_owner'] = rejected(lambda: property_info(model, 'time/waterlevini', 'm'))
            record['controls']['chezy_not_manning'] = rejected(lambda: property_info(model, 'physics/uniffrictcoef', 's m-1/3'))
            for key in ('wrong_unit', 'wrong_owner', 'chezy_not_manning'):
                record['controls'][key]['mechanism'] = 'explicit metadata/law protocol guard before setter'
            baseline(model, 'chezy')
            export(model, 'cases/control/rejected')
            prop.Value = Double(float(previous))
            assert number(prop.Value) == previous
            export(model, 'cases/control/noop')
            record['controls']['noop'] = {'passed': True, 'mechanism': 'actual typed Double same-value assignment + separate raw export'}
            bad_folder = fresh_dir('negative-fm-item')
            record['controls']['unsupported_export_item'] = rejected(lambda: FMModelFileExporter().Export(Object(), os.path.join(bad_folder, 'f34.mdu')))
            record['controls']['missing_export_path'] = rejected(lambda: FMModelFileExporter().Export(model, ''))
        if case['key']:
            prop, info = property_info(model, case['key'], case['unit'])
            entry['property'] = info; entry['before'] = str(prop.Value)
            assert number(prop.Value) == number(case['before'])
            prop.Value = Double(float(case['after']))
            assert number(prop.Value) == number(case['after']), 'Typed setter readback mismatch'
            entry['after'] = str(prop.Value)
        saved = fresh_dir('cases/' + name + '/saved-project')
        saved_project = os.path.join(saved, os.path.basename(copied))
        Application.ProjectService.SaveProjectAs(saved_project)
        export(model_in(project), 'cases/' + name + '/after')
        Application.ProjectService.CloseProject(); opened = False
        assert (sha(copied), inventory(copied + '_data')) == before_copy, 'Input project was changed during SaveAs'
        project = Application.ProjectService.OpenProject(saved_project); opened = True
        model = model_in(project)
        if case['key']:
            prop, info = property_info(model, case['key'], case['unit'])
            assert number(prop.Value) == number(case['after']), 'Reopened typed value mismatch'
            entry['reopened_value'] = str(prop.Value)
        export(model, 'cases/' + name + '/reopened')
        Application.ProjectService.CloseProject(); opened = False
        entry['reopened'] = True
        record['cases'][name] = entry
    record['source_unchanged'] = (sha(original), inventory(original + '_data')) == before_original
    assert record['source_unchanged']
    record['success'] = True
except Exception:
    record['error'] = traceback.format_exc()
finally:
    if opened:
        try:
            Application.ProjectService.CloseProject(); opened = False
        except Exception:
            record['success'] = False
            record['close_error'] = traceback.format_exc()
    record['project_closed'] = not opened
    with open(local('fields-result.json'), 'w') as stream:
        json.dump(record, stream, indent=2)
print(('E014_FIELDS_EXPORT_OK:' if record['success'] else 'E014_FIELDS_EXPORT_FAILED:') + nonce)

# IronPython 2.7 inside a NEW disposable-guest console only. Never run on host.
# Startup already touched settings BEFORE this script: controller identity gate
# and an exclusive native lease are mandatory; this is not startup isolation.
import os
import json
import traceback
from System import Object
from System.Diagnostics import Process
from DeltaShell.Plugins.FMSuite.FlowFM.IO.ImportExport.Exporters import FMModelFileExporter

root = os.environ['P08_EXPORT_ROOT']
nonce = os.environ['P08_EXPORT_NONCE']
request_path = os.path.join(root, 'request.json')
with open(request_path) as stream:
    request = json.load(stream)
assert request['nonce'] == nonce
assert request['kind'] == 'P08_disposable_guest_export_only'
assert request['engine_execution'] is False


def local(relative):
    path = os.path.abspath(os.path.join(root, relative))
    assert path.lower().startswith(os.path.abspath(root).lower() + os.sep)
    return path


def record_export(exporter, item, relative):
    path = local(relative)
    assert not os.path.exists(path)
    folder = os.path.dirname(path)
    if not os.path.exists(folder):
        os.makedirs(folder)
    assert not os.listdir(folder)
    result = bool(exporter.Export(item, path))
    return {'path': relative, 'exporter_type': str(exporter.GetType().FullName),
            'exporter_name': str(exporter.Name), 'returned': result,
            'exists': os.path.isfile(path)}


record = {'kind': request['kind'], 'nonce': nonce, 'success': False,
          'pid': Process.GetCurrentProcess().Id, 'host': str(Process.GetCurrentProcess().ProcessName),
          'trigger': 'public console --run-file; not an interactive GUI export click',
          'engine_execution': False, 'exports': [], 'controls': []}
opened = False
try:
    Application.SettingsManager.SetSetting('persistenceDefault', '.dsproj')
    Application.SettingsManager.SetSetting('useNewPersistence', 'false')
    project = Application.ProjectService.OpenProject(local(request['project']))
    opened = True
    models = [item for item in project.RootFolder.Items
              if str(item.GetType().FullName) == 'DeltaShell.Plugins.FMSuite.FlowFM.Model.WaterFlowFMModel']
    assert len(models) == 1, 'Require exactly one root-level f34 FM model'
    model = models[0]
    assert str(model.Name).lower() == 'f34'
    assert model.Grid.Vertices.Count == 258 and model.Grid.Edges.Count == 479
    record['model'] = {'name': str(model.Name), 'directory_name': str(model.DirectoryName),
                       'input_file': str(model.InputFile), 'library': str(model.LibraryName),
                       'is_master_time_step': bool(model.IsMasterTimeStep),
                       'grid_vertices': model.Grid.Vertices.Count, 'grid_edges': model.Grid.Edges.Count}
    for value in (str(model.DirectoryName), str(model.InputFile)):
        assert value and not os.path.isabs(value) and os.path.basename(value) == value
        assert value not in ('.', '..') and ':' not in value
    exporters = [e for e in Application.FileExportService.GetFileExportersFor(model)
                 if str(e.GetType().FullName) == 'DeltaShell.Plugins.DelftModels.HydroModel.Export.DHydroConfigXmlExporter']
    assert len(exporters) == 1, 'Require actual registered DIMR configuration exporter'
    exporter = exporters[0]
    assert str(exporter.Name) == 'DIMR configuration' and exporter.CanExportFor(model)
    assembly = exporter.GetType().Assembly
    record['exporter_assembly'] = {'full_name': str(assembly.FullName), 'location': str(assembly.Location)}
    normal = record_export(FMModelFileExporter(), model, 'standard/f34.mdu')
    record['exports'].append(normal)
    assert normal['returned'] and normal['exists']
    for name in ('dimr-1', 'dimr-2'):
        entry = record_export(exporter, model, name + '/dimr_config.xml')
        record['exports'].append(entry)
        assert entry['returned'] and entry['exists']
    # Public supported-interface negative controls. Unsupported item returns false
    # from the exporter after its workflow validation; preserve emitted .err.
    unsupported = Object()
    assert not exporter.CanExportFor(unsupported)
    rejected = record_export(exporter, unsupported, 'negative-type/dimr_config.xml')
    record['controls'].append(rejected)
    assert rejected['returned'] is False and rejected['exists'] is False
    no_path = bool(exporter.Export(model, ''))
    record['controls'].append({'case': 'missing_export_path', 'returned': no_path})
    assert no_path is False
    record['success'] = True
except Exception:
    record['error'] = traceback.format_exc()
finally:
    if opened:
        try:
            Application.ProjectService.CloseProject()
        except Exception:
            record['success'] = False
            record['close_error'] = traceback.format_exc()
    with open(local('host-result.json'), 'w') as stream:
        json.dump(record, stream, indent=2)
if record['success']:
    print('P08_DIMR_PROJECT_EXPORT_OK:' + nonce)
else:
    print('P08_DIMR_PROJECT_EXPORT_FAILED:' + nonce)

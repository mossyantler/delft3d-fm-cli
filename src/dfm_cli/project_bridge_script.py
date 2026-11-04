"""Fixed IronPython 2.7 resource; request JSON contains data, never Python code.

Uses the public API calls exercised by E001/E002. No imports occur in CPython
when this resource is loaded. Only a separate DeltaShell.Console process runs it.
"""

SCRIPT = r'''# Fixed dfm project bridge, IronPython 2.7 / DeltaShell.Console only.
import os
import json
import hashlib
import traceback
from System import Func, String
from System.IO import Path as DotNetPath
from System.Diagnostics import Process
from DeltaShell.Plugins.FMSuite.FlowFM.Model import WaterFlowFMModel
from DeltaShell.Plugins.FMSuite.FlowFM.IO.ImportExport.Exporters import FMModelFileExporter


def inventory(folder):
    files = []
    for parent, dirs, names in os.walk(folder):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(parent, name)
            digest = hashlib.sha256()
            with open(path, 'rb') as stream:
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
            files.append({'relative_path': os.path.relpath(path, folder).replace('\\', '/'),
                          'sha256': digest.hexdigest(), 'bytes': os.path.getsize(path)})
    return sorted(files, key=lambda item: item['relative_path'])


def one_model(project):
    items = list(project.RootFolder.Items)
    models = [item for item in items if str(item.GetType().FullName) ==
              'DeltaShell.Plugins.FMSuite.FlowFM.Model.WaterFlowFMModel']
    assert len(models) == 1 and len(items) == 1, 'Expected one root FlowFM model only'
    model = models[0]
    assert str(model.Name) == request['model_name'], 'Unexpected model identity'
    model.WorkingDirectoryPathFunc = Func[String](lambda: request['model_work'])
    return model


request_path = os.environ['DFM_PROJECT_BRIDGE_REQUEST']
with open(request_path, 'r') as stream:
    request = json.load(stream)
record = {'schema_version': 1, 'run_id': request['run_id'],
          'operation': request['operation'], 'success': False,
          'project_closed': False, 'reopened': False, 'exports': []}
opened = False
try:
    process = Process.GetCurrentProcess()
    record['process_name'] = str(process.ProcessName)
    record['process_id'] = process.Id
    assert record['process_name'].lower() == 'deltashell.console', 'Console host required'
    record['temp_directory'] = str(DotNetPath.GetTempPath())
    assert os.path.normcase(os.path.abspath(record['temp_directory'])) == os.path.normcase(os.path.abspath(request['temp_directory']))
    keys = ['persistenceDefault', 'useNewPersistence']
    record['settings_before'] = dict((key, Application.SettingsManager.GetSetting(key)) for key in keys)
    Application.SettingsManager.SetSetting('persistenceDefault', '.dsproj')
    Application.SettingsManager.SetSetting('useNewPersistence', 'false')
    record['settings_after'] = dict((key, Application.SettingsManager.GetSetting(key)) for key in keys)
    assert record['settings_after'] == {'persistenceDefault': '.dsproj', 'useNewPersistence': 'false'}
    # The settings above precede every project operation. Command-line settings
    # alone arrive too late in the E001/E002 console host.
    if request['operation'] == 'import':
        assert not os.path.exists(request['project_output'])
        assert not os.path.exists(request['project_output'] + '_data')
        project = Application.ProjectService.CreateProject()
        opened = True
        model = WaterFlowFMModel()
        model.WorkingDirectoryPathFunc = Func[String](lambda: request['model_work'])
        model.ImportFromMdu(request['source_mdu'], True)
        assert str(model.Name) == request['model_name']
        project.RootFolder.Items.Add(model)
        Application.ProjectService.SaveProjectAs(request['project_output'])
        Application.ProjectService.CloseProject()
        opened = False
        record['saved_project_files'] = inventory(os.path.dirname(request['project_output']))
        project = Application.ProjectService.OpenProject(request['project_output'])
        opened = True
        record['reopened'] = True
    else:
        assert request['operation'] == 'export'
        project = Application.ProjectService.OpenProject(request['source_project'])
        opened = True
    model = one_model(project)
    record['model_count'] = 1
    record['model_name'] = str(model.Name)
    record['grid_vertices'] = model.Grid.Vertices.Count
    record['grid_edges'] = model.Grid.Edges.Count
    destination = request['export_mdu']
    assert not os.listdir(os.path.dirname(destination)), 'Export directory must be empty'
    exported = FMModelFileExporter().Export(model, destination)
    assert exported and os.path.isfile(destination), 'Model exporter did not write the requested MDU'
    record['exports'].append({'mdu': destination, 'result': bool(exported),
                              'files': inventory(os.path.dirname(destination))})
    record['success'] = True
except:
    record['success'] = False
    record['traceback'] = traceback.format_exc()
finally:
    if opened:
        try:
            Application.ProjectService.CloseProject()
            opened = False
        except:
            record['success'] = False
            record['close_traceback'] = traceback.format_exc()
    record['project_closed'] = not opened
    if request['operation'] == 'import' and record['success']:
        record['project'] = request['project_output']
        record['project_files'] = inventory(os.path.dirname(request['project_output']))
        if record['project_files'] != record['saved_project_files']:
            record['success'] = False
            record['error'] = 'Saved project changed during reopen/export/close'
    if record['success']:
        record['completion'] = 'DFM_PROJECT_BRIDGE_COMPLETED'
    temporary = request['result_path'] + '.tmp'
    with open(temporary, 'w') as stream:
        json.dump(record, stream, indent=2)
    os.rename(temporary, request['result_path'])
if record['success']:
    print('DFM_PROJECT_BRIDGE_COMPLETED:' + request['run_id'])
'''

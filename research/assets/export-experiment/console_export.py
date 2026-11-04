# IronPython 2.7 script; settings must precede project creation/opening.
import os
import json
from System.Diagnostics import Process
from DeltaShell.Plugins.FMSuite.FlowFM.IO.ImportExport.Exporters import FMModelFileExporter

root = os.environ['DFM_EXPORT_EXPERIMENT_ROOT']
Application.SettingsManager.SetSetting('persistenceDefault', '.dsproj')
Application.SettingsManager.SetSetting('useNewPersistence', 'false')
project = Application.ProjectService.OpenProject(os.path.join(root, 'gui-project', 'gui-baseline.dsproj'))
models = [item for item in project.RootFolder.Items
          if str(item.GetType().FullName) == 'DeltaShell.Plugins.FMSuite.FlowFM.Model.WaterFlowFMModel']
assert len(models) == 1
model = models[0]
record = {'process_name': str(Process.GetCurrentProcess().ProcessName),
          'model_name': str(model.Name), 'grid_vertices': model.Grid.Vertices.Count,
          'grid_edges': model.Grid.Edges.Count, 'exports': []}
for folder in ['console-export-1', 'console-export-2']:
    path = os.path.join(root, folder, 'f34.mdu')
    assert not os.listdir(os.path.dirname(path))
    exported = FMModelFileExporter().Export(model, path)
    record['exports'].append({'path': path, 'result': exported})
    assert exported
Application.ProjectService.CloseProject()
record['success'] = True
with open(os.path.join(root, 'console-export-result.json'), 'w') as stream:
    json.dump(record, stream, indent=2)
print('EXPORT_EXPERIMENT_SCRIPT_OK')

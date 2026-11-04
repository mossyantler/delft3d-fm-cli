# IronPython 2.7 script for the installed DeltaShell.Gui.exe --run-file interface.
# A fresh GUI process and fresh experiment output folders are required.
import os
import json
import traceback
from System import Func, String
from System.Diagnostics import Process
from DeltaShell.Plugins.FMSuite.FlowFM.Model import WaterFlowFMModel
from DeltaShell.Plugins.FMSuite.FlowFM.IO.ImportExport.Exporters import FMModelFileExporter

root = os.environ['DFM_EXPORT_EXPERIMENT_ROOT']
project_path = os.path.join(root, 'gui-project', 'gui-baseline.dsproj')
result_path = os.path.join(root, 'gui-host-result.json')
record = {'operation': 'GUI-hosted project save and model export', 'menu_automation': False}
try:
    assert Gui is not None
    assert not os.path.exists(project_path)
    record['gui_type'] = str(Gui.GetType().FullName)
    record['process_name'] = str(Process.GetCurrentProcess().ProcessName)
    record['process_id'] = Process.GetCurrentProcess().Id
    project = Application.ProjectService.CreateProject()
    model = WaterFlowFMModel()
    model.WorkingDirectoryPathFunc = Func[String](lambda: os.path.join(root, 'working'))
    model.ImportFromMdu(os.path.join(root, 'source-input', 'f34.mdu'), True)
    project.RootFolder.Items.Add(model)
    Application.ProjectService.SaveProjectAs(project_path)
    record['project_path'] = project_path
    record['model_name'] = str(model.Name)
    record['grid_vertices'] = model.Grid.Vertices.Count
    record['grid_edges'] = model.Grid.Edges.Count
    record['exports'] = []
    for folder in ['gui-export-1', 'gui-export-2']:
        path = os.path.join(root, folder, 'f34.mdu')
        assert not os.listdir(os.path.dirname(path))
        exported = FMModelFileExporter().Export(model, path)
        record['exports'].append({'path': path, 'result': exported})
        assert exported
    Application.ProjectService.CloseProject()
    record['project_closed'] = True
    record['success'] = True
except:
    record['success'] = False
    record['traceback'] = traceback.format_exc()
with open(result_path, 'w') as stream:
    json.dump(record, stream, indent=2)
if record['success']:
    Gui.MainWindow.Close()

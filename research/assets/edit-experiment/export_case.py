# IronPython 2.7. Run each case in a separate console process and project copy.
import os
import json
from System import Double, TimeSpan
from System.Diagnostics import Process
from DeltaShell.Plugins.FMSuite.FlowFM.IO.ImportExport.Exporters import FMModelFileExporter

root = os.environ['DFM_EXPORT_EXPERIMENT_ROOT']
with open(os.path.join(root, 'case.json')) as stream:
    settings = json.load(stream)
assert settings['case'] in ['control', 'scalar', 'boundary']
Application.SettingsManager.SetSetting('persistenceDefault', '.dsproj')
Application.SettingsManager.SetSetting('useNewPersistence', 'false')
project = Application.ProjectService.OpenProject(os.path.join(root, 'project', 'gui-baseline.dsproj'))
models = [item for item in project.RootFolder.Items
          if str(item.GetType().FullName) == 'DeltaShell.Plugins.FMSuite.FlowFM.Model.WaterFlowFMModel']
assert len(models) == 1
model = models[0]
assert os.path.normcase(os.path.abspath(model.MduFilePath)).startswith(os.path.normcase(os.path.join(root, 'project') + os.sep))

def boundary_state():
    state = []
    for boundary_set in model.BoundaryConditionSets:
        for condition in boundary_set.BoundaryConditions:
            item = {'name': str(condition.Name), 'feature_name': str(condition.FeatureName),
                    'data_type': str(condition.DataType), 'quantity': str(condition.FlowQuantity),
                    'horizontally_uniform': condition.IsHorizontallyUniform, 'points': []}
            for index in condition.DataPointIndices:
                function = condition.GetDataAtPoint(index)
                item['points'].append({'index': index,
                    'arguments': [{'name': str(v.Name), 'unit': str(v.Unit), 'values': [float(x) for x in v.Values]} for v in function.Arguments],
                    'components': [{'name': str(v.Name), 'unit': str(v.Unit), 'values': [float(x) for x in v.Values]} for v in function.Components]})
            state.append(item)
    return state

prop = model.ModelDefinition.GetModelProperty('HisInterval')
owner = model.ModelDefinition.GetModelProperty('HisOutputDeltaT')
record = {'case': settings['case'], 'process_name': str(Process.GetCurrentProcess().ProcessName),
          'model_name': str(model.Name), 'mdu_path': str(model.MduFilePath),
          'scalar_before': str(prop.GetValueAsString()), 'boundary_before': boundary_state()}
assert record['scalar_before'] == '300'
assert float(owner.Value.TotalSeconds) == 300.0

if settings['case'] == 'scalar':
    owner.Value = TimeSpan.FromSeconds(600)
    record['scalar_edit'] = {'mdu_key': 'output/HisInterval', 'owner': 'HisOutputDeltaT',
                             'owner_type': 'System.TimeSpan', 'before': 300, 'after': 600, 'unit': 's'}
elif settings['case'] == 'boundary':
    candidates = [condition for b in model.BoundaryConditionSets for condition in b.BoundaryConditions
                  if str(condition.FeatureName) == 'L1' and str(condition.DataType) == 'Harmonics']
    assert len(candidates) == 1
    condition = candidates[0]
    assert not condition.IsHorizontallyUniform
    assert list(condition.DataPointIndices) == [0, 6, 12]
    function = condition.GetDataAtPoint(0)
    assert function.Arguments.Count == 1
    argument = function.Arguments[0]
    assert str(argument.Name) == 'Frequency' and str(argument.Unit) == 'deg/h'
    row = [i for i in range(argument.Values.Count) if abs(float(argument.Values[i]) - 28.8) < 1.e-10]
    assert len(row) == 1
    amplitude = [v for v in function.Components if str(v.Name) == 'Amplitude']
    assert len(amplitude) == 1 and str(amplitude[0].Unit) == 'm'
    assert float(amplitude[0].Values[row[0]]) == 1.5
    amplitude[0].Values[row[0]] = Double(1.75)
    record['boundary_edit'] = {'feature': 'L1', 'point_index_zero_based': 0,
                               'exported_support_name': 'L1_0001', 'frequency_deg_per_hour': 28.8,
                               'period_minutes': 750, 'row_index_zero_based': row[0],
                               'component': 'Amplitude', 'unit': 'm', 'before': 1.5, 'after': 1.75}

record['scalar_after'] = str(owner.GetValueAsString())
record['raw_scalar_before_export'] = str(prop.GetValueAsString())
record['boundary_after'] = boundary_state()
if settings['case'] == 'scalar':
    assert record['scalar_after'] == '600'
    assert record['boundary_before'] == record['boundary_after']
else:
    assert record['scalar_before'] == record['scalar_after']
if settings['case'] == 'control':
    assert record['boundary_before'] == record['boundary_after']
if settings['case'] == 'boundary':
    expected = json.loads(json.dumps(record['boundary_before']))
    assert len(expected) == 1
    point = [p for p in expected[0]['points'] if p['index'] == 0][0]
    component = [c for c in point['components'] if c['name'] == 'Amplitude'][0]
    assert component['values'] == [0.0, 1.5]
    component['values'][1] = 1.75
    assert expected == record['boundary_after']
record['exports'] = []
for folder in ['export-1', 'export-2']:
    path = os.path.join(root, folder, 'f34.mdu')
    assert not os.listdir(os.path.dirname(path))
    exported = FMModelFileExporter().Export(model, path)
    assert exported
    section = ''
    history_values = []
    with open(path) as stream:
        for line in stream:
            line = line.split('#', 1)[0].strip()
            if line.startswith('[') and line.endswith(']'):
                section = line[1:-1].strip().lower()
            elif section == 'output' and '=' in line:
                key, value = line.split('=', 1)
                if key.strip().lower() == 'hisinterval':
                    history_values.append(value.strip())
    expected_interval = '600' if settings['case'] == 'scalar' else '300'
    assert history_values == [expected_interval]
    record['exports'].append({'path': path, 'success': exported, 'verified_hisinterval': history_values[0]})
Application.ProjectService.CloseProject()
record['success'] = True
with open(os.path.join(root, 'edit-result.json'), 'w') as stream:
    json.dump(record, stream, indent=2)
print('EXPORT_EXPERIMENT_SCRIPT_OK')

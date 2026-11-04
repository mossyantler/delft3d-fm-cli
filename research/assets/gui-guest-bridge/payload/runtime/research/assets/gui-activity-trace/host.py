# E007/R01 v1, IronPython 2.7 GUI-hosted script; NEVER launch manually.
# The Phase A controller never launches this. See README startup isolation blocker.
import os
import json
import time
import traceback
import clr
from System import Func, String
from System.Diagnostics import Process
from System.IO import Path


def private_path(root, value):
    value = os.path.abspath(str(value))
    prefix = os.path.abspath(root).rstrip('\\/') + os.sep
    if not value.lower().startswith(prefix.lower()):
        raise RuntimeError('Non-private host path: ' + value)
    # Owner also rejects reparse points using filesystem metadata.
    return value


def read_gate(name, nonce, identity, timeout=15):
    path = os.path.join(root, 'protocol', name + '.json')
    deadline = time.time() + timeout
    while not os.path.isfile(path) and time.time() < deadline:
        time.sleep(0.05)
    with open(path, 'rb') as stream:
        value = json.loads(stream.read())
    if value.get('nonce') != nonce or value.get('identity') != identity:
        raise RuntimeError('Owner protocol identity mismatch: ' + name)
    return value


def emit(name, value):
    path = os.path.join(root, 'protocol', name + '.json')
    if os.path.exists(path):
        raise RuntimeError('Protocol record already exists: ' + name)
    with open(path + '.new', 'wb') as stream:
        stream.write(json.dumps(value, indent=2).encode('utf-8'))
    os.rename(path + '.new', path)


root = os.environ.get('DFM_E007_ROOT')
nonce = os.environ.get('DFM_E007_NONCE')
if not root or not nonce or len(nonce) != 64:
    # An existing GUI receiving a relayed command has no experiment env. Do not
    # access its Application/Gui objects, close its windows or write its settings.
    raise RuntimeError('No private owner challenge environment')

process = Process.GetCurrentProcess()
deadline = time.time() + 15
challenge_path = os.path.join(root, 'protocol', 'challenge.json')
while not os.path.isfile(challenge_path) and time.time() < deadline:
    time.sleep(0.05)
with open(challenge_path, 'rb') as stream:
    challenge = json.loads(stream.read())
identity = challenge['identity']
if challenge.get('schema') != 1 or challenge.get('nonce') != nonce or identity['pid'] != process.Id:
    # No cleanup/GUI operations on an identity mismatch.
    raise RuntimeError('Script not running in freshly launched PID')

confirmed = False
project_proven = False
result = {'schema': 1, 'nonce': nonce, 'identity': identity,
          'trigger': 'gui_hosted_script', 'state': 'failed',
          'interactive_button_verified': False}
try:
    temp = private_path(root, Path.GetTempPath())
    # CodeDom compiler and all scratch files inherit the same Job/private TEMP.
    clr.AddReference('Microsoft.CSharp')
    from Microsoft.CSharp import CSharpCodeProvider
    from System.CodeDom.Compiler import CompilerParameters, TempFileCollection
    provider = CSharpCodeProvider()
    parameters = CompilerParameters()
    parameters.GenerateExecutable = False
    parameters.GenerateInMemory = True
    parameters.TempFiles = TempFileCollection(temp, False)
    guard_source = os.path.join(root, 'harness', 'OwnedHostGuard.cs')
    compiled = provider.CompileAssemblyFromFile(parameters, guard_source)
    if compiled.Errors.HasErrors:
        raise RuntimeError('Guard compilation failed: ' + str(compiled.Errors[0]))
    guard = compiled.CompiledAssembly.GetType('OwnedHostGuard')
    from System import Array, Object, UInt32, Int64
    in_job = guard.GetMethod('Confirm').Invoke(None, Array[Object]([
        UInt32(identity['pid']), Int64.Parse(identity['creation_time_100ns'])]))
    confirmed = True
    clr.AddReference('System.Configuration')
    from System.Configuration import ConfigurationManager, ConfigurationUserLevel
    from System import AppDomain
    providers = [assembly.GetType('DeltaShell.Gui.PortableSettingsProvider')
                 for assembly in AppDomain.CurrentDomain.GetAssemblies()]
    providers = [provider_type for provider_type in providers if provider_type is not None]
    if len(providers) != 1:
        raise RuntimeError('Actual GUI portable settings provider unavailable/ambiguous')
    portable_config = providers[0].GetProperty('SettingsFileName').GetValue(None, None)
    paths = {'temp': temp,
             'settings': str(Application.GetUserSettingsDirectoryPath()),
             'portable_user_config': str(portable_config),
             'core_user_config_local': str(ConfigurationManager.OpenExeConfiguration(
                 ConfigurationUserLevel.PerUserRoamingAndLocal).FilePath),
             'core_user_config_roaming': str(ConfigurationManager.OpenExeConfiguration(
                 ConfigurationUserLevel.PerUserRoaming).FilePath)}
    # Always retain actual returned paths; rejection is evidence, not relocation.
    emit('handshake', {'schema': 1, 'nonce': nonce, 'identity': identity,
                      'in_job': bool(in_job), 'paths': paths})
    for path in paths.values():
        private_path(root, path)
    read_gate('project-go', nonce, identity)
    if Gui is None or Application.IsActivityRunning():
        raise RuntimeError('Host is not an idle GUI')
    if Application.Project is not None and Application.Project.RootFolder.Items.Count != 0:
        raise RuntimeError('Refuse nonempty startup project')
    if not callable(getattr(Application, 'RunActivity', None)):
        raise RuntimeError('Documented RunActivity API is unavailable')
    Application.SettingsManager.SetSetting('persistenceDefault', '.dsproj')
    Application.SettingsManager.SetSetting('useNewPersistence', 'false')
    from DeltaShell.Plugins.FMSuite.FlowFM.Model import WaterFlowFMModel
    project = Application.ProjectService.CreateProject()
    model = WaterFlowFMModel()
    model.WorkingDirectoryPathFunc = Func[String](lambda: os.path.join(root, 'working'))
    model.ImportFromMdu(os.path.join(root, 'input', 'f34.mdu'), True)
    project.RootFolder.Items.Add(model)
    project_path = os.path.join(root, 'project', 'trace.dsproj')
    if os.path.exists(project_path):
        raise RuntimeError('Project already exists')
    Application.ProjectService.SaveProjectAs(project_path)
    project_paths = {'project': str(Application.ProjectFilePath),
                     'data': str(Application.ProjectDataDirectory),
                     'input_mdu': str(model.MduFilePath),
                     'working': str(model.WorkingDirectoryPath),
                     'dimr_export': str(model.DimrExportDirectoryPath)}
    for path in project_paths.values():
        private_path(root, path)
    if os.path.normcase(os.path.abspath(project_paths['project'])) != os.path.normcase(project_path):
        raise RuntimeError('Saved project path differs')
    with open(os.path.join(root, 'fixture.json'), 'rb') as stream:
        fixture = json.loads(stream.read())
    clock = fixture['model_clock']
    if model.StartTime.ToString('s') != clock['start'] or model.StopTime.ToString('s') != clock['stop']:
        raise RuntimeError('Imported GUI model clock differs from short fixture')
    project_proven = True
    emit('project-ready', {'schema': 1, 'nonce': nonce, 'identity': identity,
                          'paths': project_paths, 'model_start': model.StartTime.ToString('s'),
                          'model_stop': model.StopTime.ToString('s'), 'model_name': str(model.Name)})
    read_gate('run-go', nonce, identity)
    result['api'] = 'Application.RunActivity(model)'
    Application.RunActivity(model)
    result.update(api_returned=True, activity_status=str(model.Status),
                  current_time=model.CurrentTime.ToString('s'), stop_time=model.StopTime.ToString('s'))
    if Application.IsActivityRunning() or str(model.Status) != 'Done' or model.CurrentTime != model.StopTime:
        raise RuntimeError('RunActivity returned without confirmed synchronous completion')
    result['state'] = 'returned_done_pending_output_and_ownership_verification'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    # Result state alone never establishes usable output or successful cleanup.
    if confirmed:
        emit('result', result)
    if confirmed and project_proven and not Application.IsActivityRunning():
        Application.ProjectService.CloseProject()
        Gui.MainWindow.Close()

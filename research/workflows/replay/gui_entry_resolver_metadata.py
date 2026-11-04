"""Read PE/ECMA-335 metadata and bounded CIL bytes; never load a CLR assembly.

Uses the already collected dnfile/pefile parsers. No reflection, subprocess,
target getter, assembly loader, JIT, native import or application entrypoint.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import logging
from pathlib import Path
import struct


class EvidenceError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(condition, code, message):
    if not condition:
        raise EvidenceError(code, message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def compressed_uint(data, offset=0):
    require(offset < len(data), "metadata_truncated", "Missing compressed integer")
    first = data[offset]
    size = 1 if first < 0x80 else 2 if first < 0xc0 else 4 if first < 0xe0 else 0
    require(size and offset + size <= len(data), "metadata_compressed", "Invalid compressed integer")
    mask = {1: 0x7f, 2: 0x3f, 4: 0x1f}[size]
    value = first & mask
    for byte in data[offset + 1:offset + size]:
        value = value * 256 + byte
    return value, offset + size


def attribute_string(data):
    require(data[:2] == b"\x01\0", "attribute_format", "Custom attribute prolog differs")
    if data[2:3] == b"\xff":
        return None
    size, offset = compressed_uint(data, 2)
    require(offset + size + 2 == len(data) and data[-2:] == b"\0\0",
            "attribute_format", "Only a single fixed string and no named attributes is decoded")
    return data[offset:offset + size].decode("utf-8", errors="strict")


def framework_attribute(data):
    require(data[:2] == b"\x01\0", "attribute_format", "Invalid target framework attribute")
    size, offset = compressed_uint(data, 2)
    value = data[offset:offset+size].decode("utf-8");offset += size
    require(offset+2 <= len(data),"attribute_format","Missing named argument count")
    count = int.from_bytes(data[offset:offset+2],"little");offset += 2
    named = {}
    for _ in range(count):
        require(data[offset:offset+2] == b"\x54\x0e","attribute_format","Unsupported named attribute argument")
        offset += 2
        length, offset = compressed_uint(data,offset)
        name = data[offset:offset+length].decode("utf-8");offset += length
        length, offset = compressed_uint(data,offset)
        text = data[offset:offset+length].decode("utf-8");offset += length
        require(name not in named,"attribute_format","Duplicate named argument")
        named[name] = text
    require(offset == len(data),"attribute_format","Trailing target framework attribute bytes")
    return {"fixed_string":value,"named_properties":named}


def opcode_table():
    result = {}
    def add(code, name, size=0): result[code] = (name, size)
    for code, name in enumerate("nop break ldarg.0 ldarg.1 ldarg.2 ldarg.3 ldloc.0 ldloc.1 ldloc.2 ldloc.3 stloc.0 stloc.1 stloc.2 stloc.3".split()): add(code, name)
    for code, name in enumerate("ldarg.s ldarga.s starg.s ldloc.s ldloca.s stloc.s".split(), 0x0e): add(code, name, 1)
    for code, name in enumerate("ldnull ldc.i4.m1 ldc.i4.0 ldc.i4.1 ldc.i4.2 ldc.i4.3 ldc.i4.4 ldc.i4.5 ldc.i4.6 ldc.i4.7 ldc.i4.8".split(), 0x14): add(code, name)
    for code, name, size in ((0x1f,"ldc.i4.s",1),(0x20,"ldc.i4",4),(0x21,"ldc.i8",8),(0x22,"ldc.r4",4),(0x23,"ldc.r8",8),
                             (0x25,"dup",0),(0x26,"pop",0),(0x27,"jmp",4),(0x28,"call",4),(0x29,"calli",4),(0x2a,"ret",0)):
        add(code,name,size)
    branches = "br brfalse brtrue beq bge bgt ble blt bne.un bge.un bgt.un ble.un blt.un".split()
    for index, name in enumerate(branches): add(0x2b+index,name+".s",1); add(0x38+index,name,4)
    add(0x45,"switch",-1)
    for code in range(0x46,0x6f): add(code,"op_"+format(code,"02x"))
    for code,name in ((0x6f,"callvirt"),(0x70,"cpobj"),(0x71,"ldobj"),(0x72,"ldstr"),(0x73,"newobj"),(0x74,"castclass"),(0x75,"isinst"),
                      (0x79,"unbox"),(0x7b,"ldfld"),(0x7c,"ldflda"),(0x7d,"stfld"),(0x7e,"ldsfld"),(0x7f,"ldsflda"),(0x80,"stsfld"),(0x81,"stobj"),
                      (0x8c,"box"),(0x8d,"newarr"),(0x8f,"ldelema"),(0xa3,"ldelem"),(0xa4,"stelem"),(0xa5,"unbox.any"),
                      (0xc2,"refanyval"),(0xc6,"mkrefany"),(0xd0,"ldtoken")):
        add(code,name,4)
    for code in [0x76,0x7a,0x8e,*range(0x82,0x8c),*range(0x90,0xa3),*range(0xb3,0xbb),0xc3,*range(0xd1,0xdd),0xdf,0xe0]: add(code,"op_"+format(code,"02x"))
    add(0xdd,"leave",4);add(0xde,"leave.s",1)
    for code,name in ((0x00,"arglist"),(0x01,"ceq"),(0x02,"cgt"),(0x03,"cgt.un"),(0x04,"clt"),(0x05,"clt.un"),
                      (0x0f,"localloc"),(0x11,"endfilter"),(0x13,"volatile."),(0x14,"tail."),(0x17,"cpblk"),(0x18,"initblk"),
                      (0x1a,"rethrow"),(0x1d,"refanytype"),(0x1e,"readonly.")):
        add(0xfe00|code,name)
    for code,name,size in ((6,"ldftn",4),(7,"ldvirtftn",4),(9,"ldarg",2),(10,"ldarga",2),(11,"starg",2),(12,"ldloc",2),
                           (13,"ldloca",2),(14,"stloc",2),(18,"unaligned.",1),(21,"initobj",4),(22,"constrained.",4),(25,"no.",1),(28,"sizeof",4)):
        add(0xfe00|code,name,size)
    return result


OPCODES = opcode_table()
TOKEN_OPS = {"jmp","call","calli","callvirt","cpobj","ldobj","ldstr","newobj","castclass","isinst","unbox",
             "ldfld","ldflda","stfld","ldsfld","ldsflda","stsfld","stobj","box","newarr","ldelema","ldelem","stelem",
             "unbox.any","refanyval","mkrefany","ldtoken","ldftn","ldvirtftn","initobj","constrained.","sizeof"}


def decode_il(data, file_offset, resolve):
    result, offset = [], 0
    while offset < len(data):
        start = offset
        code = data[offset];offset += 1
        if code == 0xfe:
            require(offset < len(data), "il_truncated", "Truncated two-byte CIL opcode")
            code = 0xfe00 | data[offset];offset += 1
        require(code in OPCODES, "il_opcode", "Unrecognized/reserved CIL opcode at " + hex(start))
        name, size = OPCODES[code]
        if size == -1:
            require(offset + 4 <= len(data), "il_truncated", "Truncated switch count")
            count = int.from_bytes(data[offset:offset+4],"little")
            require(count <= 65536,"il_bound","Switch table exceeds bound")
            size = 4 + count * 4
        require(offset + size <= len(data), "il_truncated", "CIL operand outside method")
        raw = data[offset:offset+size]
        item = {"il_offset": start, "file_offset": file_offset + start, "opcode": hex(code), "name": name,
                "instruction_bytes": data[start:offset+size].hex()}
        if size:
            item["operand_file_offset"] = file_offset + offset
            item["operand_hex"] = raw.hex()
            if name in TOKEN_OPS:
                token = int.from_bytes(raw,"little")
                item.update(token=hex(token), resolved=resolve(token))
            elif name.startswith("ldc.i4"):
                item["integer"] = int.from_bytes(raw,"little",signed=True)
        elif name.startswith("ldc.i4."):
            item["integer"] = -1 if name.endswith("m1") else int(name[-1])
        result.append(item);offset += size
    return result


class ManagedImage:
    def __init__(self, path):
        import dnfile
        self.path = Path(path)
        info = self.path.stat()
        require(0 < info.st_size <= 64*1024**2,"image_bound","Managed image exceeds 64 MiB bound")
        self.data = self.path.read_bytes()
        after = self.path.stat()
        require((info.st_size,info.st_mtime_ns)==(after.st_size,after.st_mtime_ns),"file_race","Image changed during read")
        self.diagnostics = []
        owner = self
        class Capture(logging.Handler):
            def emit(self, record):
                if len(owner.diagnostics)<1000: owner.diagnostics.append(record.getMessage())
        logger = logging.getLogger("dnfile");handler = Capture();old = logger.propagate
        logger.addHandler(handler);logger.propagate=False
        try:
            self.pe = dnfile.dnPE(data=self.data, clr_lazy_load=False)
        finally:
            logger.removeHandler(handler);logger.propagate=old
        require(self.pe.net is not None and self.pe.net.mdtables is not None,"not_managed","No CLR metadata")
        self.tables = {table.number:table for table in self.pe.net.mdtables.tables_list}
        self.owners = {}
        for row in self.pe.net.mdtables.TypeDef.rows:
            name = str(row.TypeNamespace)+"."+str(row.TypeName)
            for reference in row.MethodList:
                self.owners[(6,reference.row_index)] = name
            for reference in row.FieldList:
                self.owners[(4,reference.row_index)] = name

    def close(self): self.pe.close()
    def __enter__(self): return self
    def __exit__(self,*args): self.close()

    def resolve_token(self, token):
        table_id,index = token>>24,token&0xffffff
        if table_id==0x70:
            value = self.pe.net.user_strings.get(index)
            require(value is not None,"metadata_token","User string token does not resolve")
            return {"kind":"user_string","value":str(value)}
        table=self.tables.get(table_id)
        require(table is not None and 0 < index <= len(table.rows),"metadata_token","Token outside metadata table")
        row=table.rows[index-1]
        record={"table":table.name,"index":index}
        if table_id in (4,6):
            record.update(owner=self.owners.get((table_id,index),"<unknown>"),name=str(row.Name))
        elif table_id in (1,2):
            record.update(owner=str(row.TypeNamespace),name=str(row.TypeName))
            if table_id==1 and row.ResolutionScope.row_index:
                scope=row.ResolutionScope
                if scope.table.name=="AssemblyRef":record["assembly_scope"]=str(scope.row.Name)
        elif table_id==10:
            parent=row.Class
            record.update(name=str(row.Name),signature_hex=bytes(row.Signature.value).hex())
            if parent.table is not None and parent.row_index:
                parent_record=self.resolve_token((parent.table.number<<24)|parent.row_index)
                record["owner"]=parent_record.get("full_name",parent_record.get("name","<unknown>"))
                if "assembly_scope" in parent_record:record["assembly_scope"]=parent_record["assembly_scope"]
        elif table_id==43:
            ref=row.Method
            record.update(method=self.resolve_token((ref.table.number<<24)|ref.row_index),instantiation_hex=bytes(row.Instantiation.value).hex())
        elif table_id==27:record["signature_hex"]=bytes(row.Signature.value).hex()
        if "name" in record:
            sep="." if table_id in (1,2) else "::"
            record["full_name"]=(record.get("owner","")+sep+record["name"]).lstrip(".")
        return record

    def method_record(self, token):
        require(token>>24==6,"method_token","Expected MethodDef token")
        result=self.resolve_token(token)
        row=self.tables[6].rows[(token&0xffffff)-1]
        result.update(token=hex(token),rva=row.Rva,signature_hex=bytes(row.Signature.value).hex(),
                      internal_call=bool(row.ImplFlags.miInternalCall),native=bool(row.ImplFlags.miNative),
                      runtime=bool(row.ImplFlags.miRuntime))
        if not row.Rva:
            result["body_state"]="no_managed_body";return result
        offset=self.pe.get_offset_from_rva(row.Rva)
        require(0 <= offset < len(self.data),"method_rva","Method RVA outside file")
        first=self.data[offset]
        if first&3==2:
            header,size=1,first>>2
        elif first&3==3:
            require(offset+12<=len(self.data),"il_header","Truncated fat method header")
            flags=struct.unpack_from("<H",self.data,offset)[0]
            header=(flags>>12)*4;size=struct.unpack_from("<I",self.data,offset+4)[0]
            require(12<=header<=60,"il_header","Invalid fat method header")
            result["local_signature_token"]=hex(struct.unpack_from("<I",self.data,offset+8)[0])
        else:raise EvidenceError("il_header","Method does not have a tiny/fat CIL body")
        start=offset+header
        require(size<=1024**2 and start+size<=len(self.data),"il_bound","Method body outside file/bound")
        raw=self.data[start:start+size]
        result.update(body_state="decoded",header_file_offset=offset,il_file_offset=start,il_bytes=len(raw),il_sha256=sha(raw))
        result["instructions"]=decode_il(raw,start,self.resolve_token)
        result["calls"]=[item for item in result["instructions"] if item["name"] in {"call","callvirt","newobj","jmp"}]
        result["strings"]=[item for item in result["instructions"] if item["name"]=="ldstr"]
        return result

    def methods(self, type_name, name=None):
        return [self.method_record((6<<24)|index) for (table,index),owner in self.owners.items()
                if table==6 and owner==type_name and (name is None or str(self.tables[6].rows[index-1].Name)==name)]

    def identity(self):
        assembly=self.tables[32].rows[0];module=self.tables[0].rows[0]
        key=bytes(assembly.PublicKey.value)
        token=hashlib.sha1(key).digest()[-8:][::-1].hex() if key else None
        attributes={}
        for attribute in self.tables.get(12, type("Empty",(),{"rows":[]})()).rows:
            if attribute.Parent.table is None or attribute.Parent.table.number!=32:continue
            constructor=attribute.Type
            target=self.resolve_token((constructor.table.number<<24)|constructor.row_index)
            name=target.get("owner","")
            if name in {"System.Reflection.AssemblyCompanyAttribute","System.Reflection.AssemblyProductAttribute",
                        "System.Reflection.AssemblyFileVersionAttribute","System.Reflection.AssemblyInformationalVersionAttribute",
                        "System.Runtime.Versioning.TargetFrameworkAttribute","System.Reflection.AssemblyTitleAttribute"}:
                try:value=(framework_attribute(bytes(attribute.Value.value)) if name.endswith("TargetFrameworkAttribute") else attribute_string(bytes(attribute.Value.value)))
                except EvidenceError:value={"blob_hex":bytes(attribute.Value.value).hex(),"decoded":False}
                attributes.setdefault(name,[]).append(value)
        refs=[]
        for row in (self.tables[35].rows if 35 in self.tables else []):
            refs.append({"name":str(row.Name),"version":".".join(str(getattr(row,part)) for part in ("MajorVersion","MinorVersion","BuildNumber","RevisionNumber")),
                         "culture":str(row.Culture),"public_key_or_token":bytes(row.PublicKey.value).hex()})
        return {"path":str(self.path),"sha256":sha(self.data),"bytes":len(self.data),"assembly_name":str(assembly.Name),
                "assembly_version":".".join(str(getattr(assembly,part)) for part in ("MajorVersion","MinorVersion","BuildNumber","RevisionNumber")),
                "culture":str(assembly.Culture),"public_key_token":token,"public_key_blob_sha256":sha(key) if key else None,
                "strong_name_signature_verified":False,"module_name":str(module.Name),"mvid":str(module.Mvid),
                "entry_point_token":hex(self.pe.net.struct.EntryPointTokenOrRva),"cli_flags":int(self.pe.net.struct.Flags),
                "machine":hex(self.pe.FILE_HEADER.Machine),"pe_optional_magic":hex(self.pe.OPTIONAL_HEADER.Magic),
                "metadata_version":self.pe.net.metadata.struct.Version.rstrip(b"\0").decode("ascii"),
                "attributes":attributes,"assembly_references":refs,"parser_diagnostics":self.diagnostics,
                "parsers":{"dnfile":importlib.metadata.version("dnfile"),"pefile":importlib.metadata.version("pefile")},
                "target_code_executed":False}

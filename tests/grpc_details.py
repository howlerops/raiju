"""google.rpc.Status and google.rpc.ErrorInfo for the gRPC tests, built from descriptors at run time.

The grpcio-status and googleapis-common-protos packages are not needed: the two messages are declared here
from their .proto definitions (google/rpc/status.proto, google/rpc/error_details.proto) with the protobuf
package's descriptor API, and google.protobuf.Any and Struct come with protobuf itself.

  status_bytes(code, message, details)  the serialized Status; details is a list of Any messages
  error_info(reason, domain, metadata)  an Any holding an ErrorInfo
  struct_any(obj)                       an Any holding a Struct of a JSON object
  decode_status(raw)                    {code, message, details: [{type, ...}]} with ErrorInfo and Struct read
  details_of(metadata)                  decode_status of the grpc-status-details-bin entry of trailing metadata
"""
from google.protobuf import any_pb2, descriptor_pb2, descriptor_pool, json_format, struct_pb2
from google.protobuf import message_factory

ERROR_INFO_TYPE = "type.googleapis.com/google.rpc.ErrorInfo"
STRUCT_TYPE = "type.googleapis.com/google.protobuf.Struct"


def _classes():
    fd = descriptor_pb2.FileDescriptorProto(name="raiju_test_google_rpc.proto", package="google.rpc", syntax="proto3")
    fd.dependency.append("google/protobuf/any.proto")
    F = descriptor_pb2.FieldDescriptorProto
    st = fd.message_type.add(name="Status")
    st.field.add(name="code", number=1, type=F.TYPE_INT32, label=F.LABEL_OPTIONAL, json_name="code")
    st.field.add(name="message", number=2, type=F.TYPE_STRING, label=F.LABEL_OPTIONAL, json_name="message")
    st.field.add(name="details", number=3, type=F.TYPE_MESSAGE, label=F.LABEL_REPEATED, type_name=".google.protobuf.Any", json_name="details")
    ei = fd.message_type.add(name="ErrorInfo")
    ei.field.add(name="reason", number=1, type=F.TYPE_STRING, label=F.LABEL_OPTIONAL, json_name="reason")
    ei.field.add(name="domain", number=2, type=F.TYPE_STRING, label=F.LABEL_OPTIONAL, json_name="domain")
    ei.field.add(name="metadata", number=3, type=F.TYPE_MESSAGE, label=F.LABEL_REPEATED, type_name=".google.rpc.ErrorInfo.MetadataEntry", json_name="metadata")
    ent = ei.nested_type.add(name="MetadataEntry")
    ent.field.add(name="key", number=1, type=F.TYPE_STRING, label=F.LABEL_OPTIONAL, json_name="key")
    ent.field.add(name="value", number=2, type=F.TYPE_STRING, label=F.LABEL_OPTIONAL, json_name="value")
    ent.options.map_entry = True
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(descriptor_pb2.FileDescriptorProto.FromString(any_pb2.DESCRIPTOR.serialized_pb).SerializeToString())
    pool.AddSerializedFile(fd.SerializeToString())
    status = message_factory.GetMessageClass(pool.FindMessageTypeByName("google.rpc.Status"))
    info = message_factory.GetMessageClass(pool.FindMessageTypeByName("google.rpc.ErrorInfo"))
    return status, info


Status, ErrorInfo = _classes()


def error_info(reason, domain, metadata=None):
    e = ErrorInfo(reason=reason, domain=domain)
    for k, v in (metadata or {}).items():
        e.metadata[k] = v
    return {"type_url": ERROR_INFO_TYPE, "value": e.SerializeToString(deterministic=True)}


def struct_any(obj):
    s = struct_pb2.Struct()
    s.update(obj)
    return {"type_url": STRUCT_TYPE, "value": s.SerializeToString(deterministic=True)}


def status_bytes(code, message, details=()):
    st = Status(code=code, message=message)
    for d in details:
        a = st.details.add()
        a.type_url = d["type_url"]
        a.value = d["value"]
    return st.SerializeToString(deterministic=True)


def decode_status(raw):
    st = Status.FromString(raw)
    out = {"code": st.code, "message": st.message, "details": []}
    for a in st.details:
        if a.type_url == ERROR_INFO_TYPE:
            e = ErrorInfo.FromString(a.value)
            out["details"].append({"type": "ErrorInfo", "reason": e.reason, "domain": e.domain, "metadata": dict(e.metadata)})
        elif a.type_url == STRUCT_TYPE:
            s = struct_pb2.Struct.FromString(a.value)
            out["details"].append({"type": "Struct", "value": json_format.MessageToDict(s)})
        else:
            out["details"].append({"type": a.type_url})
    return out


def details_of(metadata):
    """The decoded grpc-status-details-bin of a call's trailing metadata (grpcio gives -bin values as bytes), or None."""
    for k, v in metadata or ():
        if k == "grpc-status-details-bin":
            return decode_status(v if isinstance(v, bytes) else v.encode())
    return None

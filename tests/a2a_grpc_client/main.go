// A gRPC client for tests/e2e.py: it talks lf.a2a.v1 to the gateway's A2A gRPC listener, as an A2A SDK client does.
//
// The success cases use the SDK's own gRPC transport (a2agrpc.NewGRPCTransport, from a2a-go v2.5.0), so the
// gateway is checked against the client the SDK ships. The error cases call the generated stub directly, because the
// SDK turns a status into an A2A error and drops the gRPC code the gateway's answer carries. Each case prints one JSON
// line: its path (sdk or stub), the gRPC code, the message, and the result or the events.
//
// Flags: -addr (the listener), -domain (server.a2a_grpc_base_domain), -agent (the agent's name), -key (a virtual key
// granted to the agent), -nogrant (a virtual key without the grant), -push (the push callback URL).
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/a2aproject/a2a-go/v2/a2a"
	"github.com/a2aproject/a2a-go/v2/a2aclient"
	a2agrpc "github.com/a2aproject/a2a-go/v2/a2agrpc/v1"
	a2apb "github.com/a2aproject/a2a-go/v2/a2apb/v1"
	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/structpb"
)

type result struct {
	Case    string   `json:"case"`
	Path    string   `json:"path"`
	Code    string   `json:"code"`
	Message string   `json:"message"`
	Result  string   `json:"result,omitempty"`
	Events  []string `json:"events,omitempty"`
	// the google.rpc.ErrorInfo of the status details (grpc-status-details-bin), and the Struct details
	Reason   string            `json:"reason,omitempty"`
	Domain   string            `json:"domain,omitempty"`
	Metadata map[string]string `json:"metadata,omitempty"`
	Structs  []string          `json:"structs,omitempty"`
	// the A2A error the SDK read from the status (the sdk path's errors)
	A2A string `json:"a2a,omitempty"`
}

func emit(r result) {
	b, _ := json.Marshal(r)
	fmt.Println(string(b))
}

// The gRPC status names as the specification writes them.
var names = map[codes.Code]string{
	codes.OK:                 "OK",
	codes.Canceled:           "CANCELLED",
	codes.Unknown:            "UNKNOWN",
	codes.InvalidArgument:    "INVALID_ARGUMENT",
	codes.DeadlineExceeded:   "DEADLINE_EXCEEDED",
	codes.NotFound:           "NOT_FOUND",
	codes.AlreadyExists:      "ALREADY_EXISTS",
	codes.PermissionDenied:   "PERMISSION_DENIED",
	codes.ResourceExhausted:  "RESOURCE_EXHAUSTED",
	codes.FailedPrecondition: "FAILED_PRECONDITION",
	codes.Aborted:            "ABORTED",
	codes.OutOfRange:         "OUT_OF_RANGE",
	codes.Unimplemented:      "UNIMPLEMENTED",
	codes.Internal:           "INTERNAL",
	codes.Unavailable:        "UNAVAILABLE",
	codes.DataLoss:           "DATA_LOSS",
	codes.Unauthenticated:    "UNAUTHENTICATED",
}

func fail(err error) (string, string) {
	if err == nil {
		return names[codes.OK], ""
	}
	st := status.Convert(err)
	return names[st.Code()], st.Message()
}

// withDetails adds the ErrorInfo and Struct details of an error's status to its row.
func withDetails(r result, err error) result {
	if err == nil {
		return r
	}
	for _, d := range status.Convert(err).Details() {
		switch v := d.(type) {
		case *errdetails.ErrorInfo:
			r.Reason, r.Domain, r.Metadata = v.Reason, v.Domain, v.Metadata
		case *structpb.Struct:
			b, _ := json.Marshal(v.AsMap())
			r.Structs = append(r.Structs, string(b))
		}
	}
	return r
}

// The A2A error an SDK call failed with, as errors.Is finds it.
func a2aErrOf(err error) string {
	for name, sentinel := range map[string]error{"task-not-found": a2a.ErrTaskNotFound, "internal": a2a.ErrInternalError, "task-not-cancelable": a2a.ErrTaskNotCancelable, "unauthenticated": a2a.ErrUnauthenticated} {
		if errors.Is(err, sentinel) {
			return name
		}
	}
	return ""
}

// The SDK's metadata for a key: the authorization header, as an SDK client sends a virtual key.
func sdkParams(key string) a2aclient.ServiceParams {
	if key == "" {
		return nil
	}
	return a2aclient.ServiceParams{"authorization": []string{"Bearer " + key}}
}

// The stub's context: the same header as sdkParams, or none.
func stubCtx(parent context.Context, key string) context.Context {
	if key == "" {
		return parent
	}
	return metadata.AppendToOutgoingContext(parent, "authorization", "Bearer "+key)
}

func dial(addr, authority string) *grpc.ClientConn {
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithAuthority(authority))
	if err != nil {
		fmt.Fprintln(os.Stderr, "dial:", err)
		os.Exit(1)
	}
	return conn
}

func text(s string) *a2apb.Message {
	return &a2apb.Message{MessageId: "m-" + s, Role: a2apb.Role_ROLE_USER, Parts: []*a2apb.Part{{Content: &a2apb.Part_Text{Text: s}}}}
}

func main() {
	addr := flag.String("addr", "127.0.0.1:18245", "the gateway's A2A gRPC listener")
	domain := flag.String("domain", "gw.test", "the base domain the agents are served under")
	agent := flag.String("agent", "grpc", "the agent's name")
	key := flag.String("key", "", "a virtual key granted to the agent")
	nogrant := flag.String("nogrant", "", "a virtual key without the agent's grant")
	push := flag.String("push", "", "the push callback URL")
	precard := flag.Bool("precard", false, "one call, made before the agent's card is fetched: its status and message only")
	flag.Parse()

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	authority := *agent + "." + *domain

	if *precard {
		// the card is not fetched yet: the gate refuses the call as UNAVAILABLE with the card's message
		cn := dial(*addr, authority)
		defer cn.Close()
		_, err := a2apb.NewA2AServiceClient(cn).GetTask(stubCtx(ctx, *key), &a2apb.GetTaskRequest{Id: "precard-task"})
		c, m := fail(err)
		emit(result{Case: "precard", Path: "stub", Code: c, Message: m})
		return
	}

	// ---- the SDK's transport: the methods of a working client ----
	conn := dial(*addr, authority)
	defer conn.Close()
	tr := a2agrpc.NewGRPCTransport(conn)

	taskID := ""
	res, err := tr.SendMessage(ctx, sdkParams(*key), &a2a.SendMessageRequest{Message: a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("hi-grpc"))})
	c, m := fail(err)
	if err == nil {
		b, _ := json.Marshal(res)
		var t struct {
			Task struct {
				ID string `json:"id"`
			} `json:"task"`
			ID string `json:"id"`
		}
		_ = json.Unmarshal(b, &t)
		taskID = t.Task.ID
		if taskID == "" {
			taskID = t.ID
		}
		emit(result{Case: "send-message", Path: "sdk", Code: c, Message: m, Result: string(b)})
	} else {
		emit(result{Case: "send-message", Path: "sdk", Code: c, Message: m})
	}

	var events []string
	var streamErr error
	for ev, e := range tr.SendStreamingMessage(ctx, sdkParams(*key), &a2a.SendMessageRequest{Message: a2a.NewMessage(a2a.MessageRoleUser, a2a.NewTextPart("stream-grpc"))}) {
		if e != nil {
			streamErr = e
			break
		}
		b, _ := json.Marshal(ev)
		events = append(events, string(b))
	}
	c, m = fail(streamErr)
	emit(result{Case: "send-streaming-message", Path: "sdk", Code: c, Message: m, Events: events})

	got, err := tr.GetTask(ctx, sdkParams(*key), &a2a.GetTaskRequest{ID: a2a.TaskID(taskID)})
	c, m = fail(err)
	gb, _ := json.Marshal(got)
	emit(result{Case: "get-task", Path: "sdk", Code: c, Message: m, Result: string(gb)})

	canceled, err := tr.CancelTask(ctx, sdkParams(*key), &a2a.CancelTaskRequest{ID: a2a.TaskID(taskID)})
	c, m = fail(err)
	cb, _ := json.Marshal(canceled)
	emit(result{Case: "cancel-task", Path: "sdk", Code: c, Message: m, Result: string(cb)})

	created, err := tr.CreateTaskPushConfig(ctx, sdkParams(*key), &a2a.PushConfig{TaskID: a2a.TaskID(taskID), ID: "cfg-grpc", URL: *push})
	c, m = fail(err)
	crb, _ := json.Marshal(created)
	emit(result{Case: "push-create", Path: "sdk", Code: c, Message: m, Result: string(crb)})

	pushed, err := tr.GetTaskPushConfig(ctx, sdkParams(*key), &a2a.GetTaskPushConfigRequest{TaskID: a2a.TaskID(taskID), ID: "cfg-grpc"})
	c, m = fail(err)
	pb, _ := json.Marshal(pushed)
	emit(result{Case: "push-get", Path: "sdk", Code: c, Message: m, Result: string(pb)})

	listed, err := tr.ListTaskPushConfigs(ctx, sdkParams(*key), &a2a.ListTaskPushConfigRequest{TaskID: a2a.TaskID(taskID)})
	c, m = fail(err)
	lb, _ := json.Marshal(listed)
	emit(result{Case: "push-list", Path: "sdk", Code: c, Message: m, Result: string(lb)})

	err = tr.DeleteTaskPushConfig(ctx, sdkParams(*key), &a2a.DeleteTaskPushConfigRequest{TaskID: a2a.TaskID(taskID), ID: "cfg-grpc"})
	c, m = fail(err)
	emit(result{Case: "push-delete", Path: "sdk", Code: c, Message: m})

	card, err := tr.GetExtendedAgentCard(ctx, sdkParams(*key), &a2a.GetExtendedAgentCardRequest{})
	c, m = fail(err)
	kb, _ := json.Marshal(card)
	emit(result{Case: "extended-card", Path: "sdk", Code: c, Message: m, Result: string(kb)})

	events = nil
	streamErr = nil
	for ev, e := range tr.SubscribeToTask(ctx, sdkParams(*key), &a2a.SubscribeToTaskRequest{ID: a2a.TaskID(taskID)}) {
		if e != nil {
			streamErr = e
			break
		}
		b, _ := json.Marshal(ev)
		events = append(events, string(b))
	}
	c, m = fail(streamErr)
	emit(result{Case: "subscribe-to-task", Path: "sdk", Code: c, Message: m, Events: events})

	// the SDK reads the A2A error back from the status details
	_, err = tr.GetTask(ctx, sdkParams(*key), &a2a.GetTaskRequest{ID: "missing-task"})
	c, m = fail(err)
	emit(result{Case: "sdk-task-missing", Path: "sdk", Code: c, Message: m, A2A: a2aErrOf(err)})

	// ---- the stub: the status each refusal and error carries ----
	stubCall := func(name, auth, k string, call func(context.Context, a2apb.A2AServiceClient) error) {
		cn := dial(*addr, auth)
		defer cn.Close()
		err := call(stubCtx(ctx, k), a2apb.NewA2AServiceClient(cn))
		c, m := fail(err)
		emit(withDetails(result{Case: name, Path: "stub", Code: c, Message: m}, err))
	}
	getTask := func(id string) func(context.Context, a2apb.A2AServiceClient) error {
		return func(cx context.Context, s a2apb.A2AServiceClient) error {
			_, err := s.GetTask(cx, &a2apb.GetTaskRequest{Id: id})
			return err
		}
	}
	stubCall("wrong-authority", "echo.other.test", *key, getTask(taskID))
	stubCall("domain-only", *domain, *key, getTask(taskID))
	stubCall("unknown-agent", "nosuch."+*domain, *key, getTask(taskID))
	stubCall("no-key", authority, "", getTask(taskID))
	stubCall("bad-key", authority, "sk-bf-not-a-key", getTask(taskID))
	stubCall("no-grant", authority, *nogrant, getTask(taskID))
	stubCall("task-missing", authority, *key, getTask("missing-task"))
	stubCall("agent-error", authority, *key, func(cx context.Context, s a2apb.A2AServiceClient) error {
		_, err := s.SendMessage(cx, &a2apb.SendMessageRequest{Message: text("fail")})
		return err
	})
	stubCall("api-key-header", authority, "", func(cx context.Context, s a2apb.A2AServiceClient) error {
		_, err := s.GetTask(metadata.AppendToOutgoingContext(cx, "x-api-key", *key), &a2apb.GetTaskRequest{Id: taskID})
		return err
	})
}

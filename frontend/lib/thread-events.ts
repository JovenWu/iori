export const THREAD_CREATED_EVENT = "agent:thread-created";
export const THREAD_STREAMING_STATE_EVENT = "agent:thread-streaming-state";
/** A live page unmounted (navigation) while its turn was still generating — the
 * server keeps going (resumable). The sidebar watches it and notifies on finish. */
export const THREAD_STREAM_DETACHED_EVENT = "agent:thread-stream-detached";

export interface ThreadCreatedEventDetail {
  threadId: string;
  title?: string;
}

export interface ThreadStreamingStateEventDetail {
  threadId: string;
  isStreaming: boolean;
}

export interface ThreadStreamDetachedEventDetail {
  threadId: string;
}

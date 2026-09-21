export const THREAD_CREATED_EVENT = "agent:thread-created";
export const THREAD_STREAMING_STATE_EVENT = "agent:thread-streaming-state";
/** A live page unmounted (navigation) while its turn was still generating — the
 * server keeps going (resumable). The sidebar watches it and notifies on finish. */
export const THREAD_STREAM_DETACHED_EVENT = "agent:thread-stream-detached";
/** A thread's title changed (rename dialog) — the open chat header listens so
 * it never shows a stale title for the thread it's viewing. */
export const THREAD_RENAMED_EVENT = "agent:thread-renamed";
/** "New Thread" clicked while already on "/" — no navigation happens, so the
 * open ChatView resets itself (detaching any live run to the sidebar). */
export const NEW_THREAD_EVENT = "agent:new-thread";
/** A thread was deleted on any surface — other views holding it drop the row. */
export const THREAD_DELETED_EVENT = "agent:thread-deleted";

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

export interface ThreadRenamedEventDetail {
  threadId: string;
  title: string;
}

export interface ThreadDeletedEventDetail {
  threadId: string;
}

/** Dispatch one of the thread events above. */
export function emitThreadEvent<T>(type: string, detail: T) {
  window.dispatchEvent(new CustomEvent<T>(type, { detail }));
}

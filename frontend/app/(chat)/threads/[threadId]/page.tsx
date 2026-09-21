"use client";

import { useParams } from "next/navigation";

import { ChatView } from "@/components/chat-view";

export default function ThreadPage() {
  const { threadId } = useParams<{ threadId: string }>();
  return <ChatView threadId={threadId} />;
}

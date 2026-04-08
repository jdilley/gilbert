import { useState, useEffect, useRef } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MarkdownContent } from "@/components/ui/MarkdownContent";

type ScreenState = "setup" | "idle" | "loading" | "display" | "error";

interface DisplayContent {
  type: "pdf" | "image" | "markdown" | "url";
  url?: string;
  content?: string;
}

export function ScreensPage() {
  const [screenName, setScreenName] = useState("");
  const [defaultUrl, setDefaultUrl] = useState("");
  const [state, setState] = useState<ScreenState>("setup");
  const [displayContent, setDisplayContent] = useState<DisplayContent | null>(
    null,
  );
  const [errorMessage, setErrorMessage] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);

  function connect() {
    if (!screenName.trim()) return;

    setState("idle");
    const params = new URLSearchParams({ name: screenName.trim() });
    if (defaultUrl.trim()) params.set("default_url", defaultUrl.trim());

    const es = new EventSource(`/screens/stream?${params}`);
    eventSourceRef.current = es;

    es.addEventListener("display_pdf", (e) => {
      const data = JSON.parse(e.data);
      setState("display");
      setDisplayContent({ type: "pdf", url: data.url });
    });

    es.addEventListener("display_image", (e) => {
      const data = JSON.parse(e.data);
      setState("display");
      setDisplayContent({ type: "image", url: data.url });
    });

    es.addEventListener("display_markdown", (e) => {
      const data = JSON.parse(e.data);
      setState("display");
      setDisplayContent({ type: "markdown", content: data.content });
    });

    es.addEventListener("display_url", (e) => {
      const data = JSON.parse(e.data);
      setState("display");
      setDisplayContent({ type: "url", url: data.url });
    });

    es.addEventListener("idle", () => {
      setState("idle");
      setDisplayContent(null);
    });

    es.addEventListener("loading", () => {
      setState("loading");
    });

    es.addEventListener("error", (e) => {
      if (e instanceof MessageEvent) {
        const data = JSON.parse(e.data);
        setState("error");
        setErrorMessage(data.message || "Unknown error");
      }
    });

    es.onerror = () => {
      setState("error");
      setErrorMessage("Connection lost. Reconnecting...");
    };
  }

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  if (state === "setup") {
    return (
      <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-6">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Screen Setup</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              value={screenName}
              onChange={(e) => setScreenName(e.target.value)}
              placeholder="Screen name"
            />
            <Input
              value={defaultUrl}
              onChange={(e) => setDefaultUrl(e.target.value)}
              placeholder="Default URL (optional)"
            />
            <Button onClick={connect} className="w-full">
              Connect
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (state === "idle") {
    return (
      <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center">
        <div className="text-center text-muted-foreground">
          <div className="text-lg font-medium">{screenName}</div>
          <div className="text-sm">Waiting for content...</div>
        </div>
      </div>
    );
  }

  if (state === "loading") {
    return (
      <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center">
        <div className="text-center text-destructive">
          <div className="text-lg font-medium">Error</div>
          <div className="text-sm">{errorMessage}</div>
        </div>
      </div>
    );
  }

  // Display state
  if (!displayContent) return null;

  switch (displayContent.type) {
    case "pdf":
      return (
        <iframe
          src={displayContent.url}
          className="w-full h-[calc(100vh-3.5rem)]"
          title="Document"
        />
      );
    case "image":
      return (
        <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-4">
          <img
            src={displayContent.url}
            alt="Screen content"
            className="max-w-full max-h-[calc(100vh-4.5rem)] object-contain"
          />
        </div>
      );
    case "markdown":
      return (
        <div className="p-8 max-w-3xl mx-auto">
          <MarkdownContent content={displayContent.content || ""} />
        </div>
      );
    case "url":
      return (
        <iframe
          src={displayContent.url}
          className="w-full h-[calc(100vh-3.5rem)]"
          title="External content"
        />
      );
    default:
      return null;
  }
}

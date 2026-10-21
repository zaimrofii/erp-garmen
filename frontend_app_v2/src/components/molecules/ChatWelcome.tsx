/**
 * ChatWelcome — empty state chat AI.
 *
 * Bukan item percakapan: tidak pernah masuk messages/history payload.
 */
export function ChatWelcome() {
  return (
    <p
      data-testid="ai-chat-welcome"
      className="px-4 py-8 text-center text-sm text-muted-foreground"
    >
      Halo! Ada yang bisa saya bantu? Saya bisa membantu analisa produk, order,
      bundle, stok, metrik produksi, dan lainnya.
    </p>
  );
}

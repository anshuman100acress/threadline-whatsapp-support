const form = document.querySelector("#chat-form");
const input = document.querySelector("#message");
const conversation = document.querySelector("#conversation");
const status = document.querySelector("#status");
const examples = [...document.querySelectorAll("[data-message]")];
const controls = [document.querySelector("#send"), ...examples];
let pending = false;

function addBubble(message, direction) {
  const bubble = document.createElement("p");
  bubble.className = "bubble " + direction;
  bubble.textContent = message;
  conversation.append(bubble);
  conversation.scrollTop = conversation.scrollHeight;
  return bubble;
}

async function send(message) {
  if (!message || pending) return;
  pending = true;
  controls.forEach(button => { button.disabled = true; });
  status.textContent = "Waiting for reply…";
  const outgoing = addBubble(message, "outgoing");
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message })
    });
    if (!response.ok) throw new Error("Chat request failed");
    const result = await response.json();
    addBubble(result.reply, "incoming");
    status.textContent = "";
  } catch {
    outgoing.remove();
    input.value ||= message;
    status.textContent = "Message could not be sent. Try again.";
  } finally {
    pending = false;
    controls.forEach(button => { button.disabled = false; });
    input.focus();
  }
}

form.addEventListener("submit", event => {
  event.preventDefault();
  if (pending) return;
  const message = input.value.trim();
  input.value = "";
  send(message);
});
examples.forEach(button => button.addEventListener("click", () => send(button.dataset.message)));

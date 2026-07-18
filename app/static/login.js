document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.querySelector("#login-error");
  error.textContent = "";
  const response = await fetch("/api/auth/login", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({password: event.target.password.value})
  });
  if (response.ok) location.href = "/";
  else error.textContent = "Sign-in failed. Check the administrator password.";
});

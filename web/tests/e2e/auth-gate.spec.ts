import {expect,test} from "@playwright/test";

test("unauthenticated users can switch between sign-in and registration",async({page})=>{
  await page.route("**/backend/api/v1/auth/session",route=>route.fulfill({status:401,contentType:"application/json",body:JSON.stringify({detail:"Authentication required"})}));
  await page.goto("/");
  await expect(page.getByRole("heading",{name:"Daily Report",exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"Sign in"})).toHaveAttribute("aria-pressed","true");
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toHaveAttribute("minlength","12");
  await page.getByRole("button",{name:"Create account"}).click();
  await expect(page.getByRole("button",{name:"Create account"})).toHaveAttribute("aria-pressed","true");
  await expect(page.getByText(/New accounts remain locked/)).toBeVisible();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("session failures expose recovery without trapping the user",async({page})=>{
  await page.route("**/backend/api/v1/auth/session",route=>route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:"Backend temporarily unavailable"})}));
  await page.goto("/");
  const recovery=page.locator("main.auth-screen .auth-card[role='alert']");
  await expect(recovery).toContainText("Backend temporarily unavailable");
  await recovery.getByRole("button",{name:"Continue to sign in"}).click();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
});

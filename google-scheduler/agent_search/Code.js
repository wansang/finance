/**
 * agent_search 워크플로우를 GitHub Actions로 트리거하는 함수
 */
function dispatchAgentSearchWorkflow() {
  var url = "https://api.github.com/repos/wansang/finance/actions/workflows/agent_search.yml/dispatches";
  var payload = JSON.stringify({ ref: "main" });
  var token = PropertiesService.getScriptProperties().getProperty("GITHUB_PAT");
  var options = {
    method: "post",
    contentType: "application/json",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": "Bearer " + token
    },
    payload: payload,
    muteHttpExceptions: true
  };
  var response = UrlFetchApp.fetch(url, options);
  Logger.log(response.getContentText());
}

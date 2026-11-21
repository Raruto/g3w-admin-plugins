@browser
Feature: Plugin preparation status

  Scenario Outline: Reload progress controls the available actions
    Given a completed preparation waiting for reload
    When the status reports web "<web>", consumer "<consumer>", consumer required "<required>" after <seconds> seconds
    Then the status contains "<message>" with level "<level>"
    And actions are "<actions>" and retry is "<retry>"

    Examples:
      | web   | consumer | required | seconds | message                           | level   | actions  | retry  |
      | true  | false    | true     | 20      | Waiting for the consumer          | info    | disabled | hidden |
      | true  | false    | true     | 60      | has not confirmed                 | warning | disabled | shown  |
      | true  | true     | true     | 20      | Web and consumer loaded           | success | enabled  | hidden |
      | true  | false    | false    | 20      | consumer is disabled              | success | enabled  | hidden |
      | false | false    | false    | 60      | web process has not confirmed     | warning | enabled  | shown  |

  Scenario: A confirmed success is hidden only after a page reload
    Given a completed preparation waiting for reload
    When the status reports web "true", consumer "true", consumer required "true" after 20 seconds
    Then the success message is visible
    When the next status poll completes
    Then the success message is visible
    When the page is reloaded
    Then the success message is hidden
    When a new preparation is confirmed
    Then the success message is visible

  Scenario: An error is not hidden after a previous success
    Given a completed preparation waiting for reload
    When the status reports web "true", consumer "true", consumer required "true" after 20 seconds
    And the page is reloaded
    And preparation fails
    Then the status contains "failure" with level "danger"

  Scenario: Pending reload remains visible after a previous success
    Given a completed preparation waiting for reload
    When the status reports web "true", consumer "true", consumer required "true" after 20 seconds
    And the page is reloaded
    And the consumer is pending again
    Then the status contains "Waiting for the consumer" with level "info"

  Scenario: Server-confirmed success is hidden when navigation is a reload
    Given a completed preparation waiting for reload
    When the server renders a confirmed success during a simulated reload
    Then the success message is hidden
    When a new preparation is confirmed
    Then the success message is visible


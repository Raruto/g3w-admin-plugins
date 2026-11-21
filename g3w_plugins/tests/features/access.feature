@backend
Feature: Secure plugin administration

  Background:
    Given an isolated plugin administration request

  Scenario: Non-superusers cannot see or change plugins
    When a non-superuser requests or changes the plugin page
    Then both requests are redirected without starting a change

  Scenario: Plugin changes require CSRF protection
    When a superuser submits a change without a CSRF token
    Then CSRF middleware rejects the request

  Scenario: A superuser can request plugin activation
    When a superuser enables panoramax
    Then background preparation starts for panoramax

  Scenario: Untrusted plugin names are rejected in both execution modes
    When a superuser submits untrusted plugin names
    Then the requests are rejected without starting preparation

  Scenario: Unsupported background execution falls back to synchronous preparation
    When a superuser disables panoramax without background support
    Then synchronous preparation is invoked

  Scenario: Reload requires a superuser and reports failures
    When a non-superuser and a superuser request a failing reload
    Then the non-superuser is redirected and the failure is reported

  Scenario: Reload is rejected during preparation
    When a superuser requests reload during preparation
    Then reload is not requested and an error is reported

  Scenario: Plugin status is restricted and reports the active phase
    When a non-superuser and a superuser request status
    Then only the superuser sees the preparation phase and an uncached response

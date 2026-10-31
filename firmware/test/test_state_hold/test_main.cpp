#include <unity.h>

#include "state_hold.hpp"

void test_never_set_never_expires() {
  StateHold hold;
  TEST_ASSERT_FALSE(hold.expired(0));
  TEST_ASSERT_FALSE(hold.expired(100000));
}

void test_expires_after_timeout_exactly_once() {
  StateHold hold;
  hold.set(5000);
  TEST_ASSERT_FALSE(hold.expired(5000 + STATE_TIMEOUT_MS - 1));
  TEST_ASSERT_TRUE(hold.expired(5000 + STATE_TIMEOUT_MS));
  TEST_ASSERT_FALSE(hold.expired(5000 + STATE_TIMEOUT_MS + 1));
}

void test_refresh_extends_the_hold() {
  StateHold hold;
  hold.set(0);
  hold.set(900);
  TEST_ASSERT_FALSE(hold.expired(1500));
  TEST_ASSERT_TRUE(hold.expired(1900));
}

void test_set_after_expiry_arms_again() {
  StateHold hold;
  hold.set(0);
  TEST_ASSERT_TRUE(hold.expired(2000));
  hold.set(3000);
  TEST_ASSERT_TRUE(hold.expired(4000));
}

void test_clear_disarms() {
  StateHold hold;
  hold.set(0);
  hold.clear();
  TEST_ASSERT_FALSE(hold.expired(5000));
}

void test_expiry_survives_millis_wraparound() {
  StateHold hold;
  hold.set(0xFFFFFF00u);
  TEST_ASSERT_FALSE(hold.expired(0xFFFFFF00u + 500));
  TEST_ASSERT_TRUE(hold.expired(0xFFFFFF00u + STATE_TIMEOUT_MS));
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_never_set_never_expires);
  RUN_TEST(test_expires_after_timeout_exactly_once);
  RUN_TEST(test_refresh_extends_the_hold);
  RUN_TEST(test_set_after_expiry_arms_again);
  RUN_TEST(test_clear_disarms);
  RUN_TEST(test_expiry_survives_millis_wraparound);
  return UNITY_END();
}

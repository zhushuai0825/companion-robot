import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class MySubscriber(Node):
    def __init__(self):
        super().__init__('my_subscriber')
        self.sub = self.create_subscription(
            String, '/chatter', self.callback, 10
        )

    def callback(self, msg):
        self.get_logger().info(f'I heard: {msg.data}')


def main():
    rclpy.init()
    node = MySubscriber()
    rclpy.spin(node)
    rclpy.shutdown()


if __name__ == '__main__':
    main()

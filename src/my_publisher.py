import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class MyPublisher(Node):
    def __init__(self):
        super().__init__('my_publisher')
        self.pub = self.create_publisher(String, '/chatter', 10)
        self.timer = self.create_timer(1.0, self.callback)
        self.count = 0

    def callback(self):
        msg = String()
        msg.data = f'Hello World: {self.count}'
        self.pub.publish(msg)
        self.get_logger().info(f'Publishing: {msg.data}')
        self.count += 1


def main():
    rclpy.init()
    node = MyPublisher()
    rclpy.spin(node)
    rclpy.shutdown()


if __name__ == '__main__':
    main()
